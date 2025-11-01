import argparse
import base64
import json
import os
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth import exceptions as gauth_exceptions


def _service_from_sa_b64(sa_b64: str):
    try:
        raw = base64.b64decode(sa_b64).decode('utf-8')
    except Exception:
        raw = sa_b64
    try:
        info = json.loads(raw)
    except Exception:
        raise SystemExit('Invalid service account JSON')
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)


def _service_from_oauth_env():
    cid = os.getenv('GDRIVE_CLIENT_ID')
    csec = os.getenv('GDRIVE_CLIENT_SECRET')
    rtok = os.getenv('GDRIVE_REFRESH_TOKEN')
    if not (cid and csec and rtok):
        return None
    # Do not request scopes explicitly; reuse scopes bound to the refresh token.
    creds = Credentials(
        token=None,
        refresh_token=rtok,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=cid,
        client_secret=csec,
    )
    try:
        creds.refresh(Request())
    except gauth_exceptions.RefreshError:
        # Invalid scope or revoked token; skip OAuth path.
        return None
    return build('drive', 'v3', credentials=creds)


def _skip_ids_from_env() -> set:
    raw = os.getenv('DRIVE_SKIP_FILE_IDS') or os.getenv('REFERENCE_CARS_DRIVE_ID')
    if not raw:
        return set()
    parts = []
    for chunk in raw.replace(',', ' ').split():
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return set(parts)


def cleanup_folder(svc, folder_id: str) -> int:
    if not folder_id:
        print('No folder id; skip cleanup')
        return 0
    skip_ids = _skip_ids_from_env()
    q = f"'{folder_id}' in parents and trashed = false"
    page_token = None
    deleted = 0
    while True:
        resp = svc.files().list(
            q=q,
            fields='nextPageToken, files(id,name)',
            pageSize=1000,
            pageToken=page_token,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        for f in resp.get('files', []):
            file_id = f.get('id')
            if file_id in skip_ids:
                print(f"skip: preserving {f.get('name')} ({file_id})")
                continue
            try:
                svc.files().delete(fileId=file_id, supportsAllDrives=True).execute()
                deleted += 1
                print(f"deleted: {f.get('name')} ({file_id})")
            except HttpError as e:
                print(f"warn: failed to delete {file_id}: {e}")
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    print(f"cleanup: removed {deleted} file(s) from folder {folder_id}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description='Delete all files in a Google Drive folder (Shared Drives supported).')
    ap.add_argument('--folder-id', required=True)
    args = ap.parse_args()

    # Prefer OAuth (user Drive) because Service Accounts lack My Drive quota
    svc = _service_from_oauth_env()
    if svc is None:
        sa_b64 = os.getenv('GDRIVE_SERVICE_ACCOUNT_JSON')
        if sa_b64:
            try:
                svc = _service_from_sa_b64(sa_b64)
            except Exception:
                svc = None
    if svc is None:
        print('No Drive credentials available; skipping cleanup')
        return 0
    return cleanup_folder(svc, args.folder_id)


if __name__ == '__main__':
    raise SystemExit(main())

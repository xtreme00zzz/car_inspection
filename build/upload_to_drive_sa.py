import argparse
import base64
import json
import os
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError, ResumableUploadError


def get_credentials(sa_json: str):
    try:
        # Allow both raw JSON and base64-encoded JSON
        if sa_json.strip().startswith('{'):
            info = json.loads(sa_json)
        else:
            info = json.loads(base64.b64decode(sa_json).decode('utf-8'))
    except Exception:
        raise SystemExit('Invalid service account JSON')
    scopes = ['https://www.googleapis.com/auth/drive.file']
    return service_account.Credentials.from_service_account_info(info, scopes=scopes)


def upload_file(creds, folder_id: str, file_path: Path, name: str | None = None) -> dict:
    svc = build('drive', 'v3', credentials=creds)
    metadata = {'name': name or file_path.name}
    if folder_id:
        metadata['parents'] = [folder_id]
    # Proactively delete existing files with the same name in the folder to avoid duplicates
    try:
        if folder_id:
            q = f"name = '{metadata['name'].replace("'", "\\'")}' and '{folder_id}' in parents and trashed = false"
        else:
            q = f"name = '{metadata['name'].replace("'", "\\'")}' and trashed = false"
        resp = svc.files().list(q=q, fields='files(id,name)', pageSize=1000,
                                supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        for f in resp.get('files', []):
            svc.files().delete(fileId=f['id'], supportsAllDrives=True).execute()
    except Exception:
        pass
    media = MediaFileUpload(str(file_path), resumable=True)
    # supportsAllDrives helps when uploading to Shared Drives
    file = svc.files().create(body=metadata, media_body=media, fields='id,name,size', supportsAllDrives=True).execute()
    fid = file['id']
    # Make public
    svc.permissions().create(fileId=fid, body={'type': 'anyone', 'role': 'reader'}, supportsAllDrives=True).execute()
    url = f'https://drive.google.com/uc?export=download&id={fid}'
    return {'id': fid, 'name': file.get('name'), 'size': int(file.get('size', 0)), 'url': url}


def main() -> int:
    ap = argparse.ArgumentParser(description='Upload a file to Google Drive via service account and print public URL.')
    ap.add_argument('--file', required=True)
    ap.add_argument('--folder-id', required=True)
    ap.add_argument('--name', default=None)
    args = ap.parse_args()

    sa_json = os.getenv('GDRIVE_SERVICE_ACCOUNT_JSON')
    if not sa_json:
        raise SystemExit('Missing GDRIVE_SERVICE_ACCOUNT_JSON env var')
    p = Path(args.file)
    if not p.exists():
        raise SystemExit(f'File not found: {p}')
    creds = get_credentials(sa_json)
    try:
        info = upload_file(creds, args.folder_id, p, args.name)
    except (ResumableUploadError, HttpError) as e:
        # Gracefully skip when service account lacks storage quota (My Drive). Allow workflow to continue.
        msg = str(getattr(e, 'error_details', '')) or str(e)
        if 'storage quota' in msg.lower() or 'storageQuotaExceeded' in msg:
            print('Service account cannot upload to My Drive (no quota). Skipping Drive upload and falling back.', flush=True)
            return 0
        raise
    # Plain output
    print(f"ID={info['id']}")
    print(f"URL={info['url']}")
    print(f"NAME={info['name']}")
    print(f"SIZE={info['size']}")
    # GitHub Actions outputs
    gh_out = os.getenv('GITHUB_OUTPUT')
    if gh_out:
        with open(gh_out, 'a', encoding='utf-8') as f:
            for k in ('id', 'url', 'name', 'size'):
                f.write(f"{k}={info[k]}\n")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

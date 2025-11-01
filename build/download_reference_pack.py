#!/usr/bin/env python3
"""
Download the reference_cars payload from Google Drive (via service account) and unpack it.

The script is intended to run in CI prior to building the Windows installer so that
the large reference dataset can live outside the git repository.

Environment variables:
  - REFERENCE_CARS_DRIVE_ID: Google Drive file id for the zipped pack (required unless --drive-id provided)
  - GDRIVE_SERVICE_ACCOUNT_JSON: Service account JSON (raw or base64) with access to the file

Usage example:
  python build/download_reference_pack.py --dest reference_cars
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


CHUNK_SIZE = 32 * 1024 * 1024  # 32 MB chunks to balance speed/memory


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Download reference_cars archive from Google Drive.')
    ap.add_argument('--drive-id', default=os.getenv('REFERENCE_CARS_DRIVE_ID'),
                    help='Google Drive file ID for the reference archive (defaults to env).')
    ap.add_argument('--dest', default='reference_cars', help='Destination folder for extracted data.')
    ap.add_argument('--artifact', default='.cache/reference_cars.zip',
                    help='Local path for the downloaded archive.')
    ap.add_argument('--force', action='store_true',
                    help='Re-download and overwrite even if destination already exists.')
    return ap.parse_args()


def ensure_service_account_credentials() -> service_account.Credentials:
    raw = os.getenv('GDRIVE_SERVICE_ACCOUNT_JSON')
    if not raw:
        raise SystemExit('GDRIVE_SERVICE_ACCOUNT_JSON environment variable is required to download from Drive.')
    try:
        data = raw.strip()
        if data.startswith('{'):
            info = json.loads(data)
        else:
            decoded = base64.b64decode(data)
            info = json.loads(decoded.decode('utf-8'))
    except Exception as exc:  # pragma: no cover - defensive
        raise SystemExit(f'Invalid service account JSON: {exc}')
    scopes = ['https://www.googleapis.com/auth/drive.readonly']
    return service_account.Credentials.from_service_account_info(info, scopes=scopes)


def download_from_drive(file_id: str, output: Path) -> None:
    creds = ensure_service_account_credentials()
    svc = build('drive', 'v3', credentials=creds)
    print(f'Downloading Google Drive file {file_id} -> {output}')
    meta = svc.files().get(fileId=file_id, fields='name,size', supportsAllDrives=True).execute()
    name = meta.get('name', 'reference_cars.zip')
    size = int(meta.get('size', 0))
    if not output.parent.exists():
        output.parent.mkdir(parents=True, exist_ok=True)
    request = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
    fh = io.FileIO(output, 'wb')
    downloader = MediaIoBaseDownload(fh, request, chunksize=CHUNK_SIZE)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f'  progress: {pct}% ({status.resumable_progress // (1024 * 1024)} MB of '
                  f'{size // (1024 * 1024) if size else "?"} MB)', flush=True)
    fh.close()
    print(f'Download complete: {name} ({size // (1024 * 1024) if size else "unknown"} MB)')


def extract_archive(archive: Path, dest: Path, *, force: bool) -> None:
    if not archive.exists():
        raise SystemExit(f'Archive not found: {archive}')
    # Short-circuit if destination is already populated and force not requested.
    if dest.exists() and any(dest.iterdir()) and not force:
        print(f'Skipping extraction: destination {dest} already populated.')
        return
    tmp_root = dest.parent / '.reference_cars_extract'
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=True)
    print(f'Extracting {archive} -> {dest}')
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tmp_root)
    except zipfile.BadZipFile as exc:
        raise SystemExit(f'Failed to unpack {archive}: {exc}')
    candidate = None
    # Prefer a folder that matches the destination name.
    for child in tmp_root.iterdir():
        if child.is_dir() and child.name == dest.name:
            candidate = child
            break
    if candidate is None:
        dirs = [p for p in tmp_root.iterdir() if p.is_dir()]
        if len(dirs) == 1:
            candidate = dirs[0]
        else:
            # If the archive contains files directly at the root, treat tmp_root as the candidate.
            candidate = tmp_root
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(candidate), str(dest))
    shutil.rmtree(tmp_root, ignore_errors=True)
    print(f'Extraction complete -> {dest}')


def main() -> int:
    args = parse_args()
    dest = Path(args.dest).resolve()
    if dest.exists() and any(dest.iterdir()) and not args.force:
        print(f'Reference cars already present at {dest}; skipping download.')
        return 0
    file_id = args.drive_id
    if not file_id:
        raise SystemExit('Reference pack Drive ID not provided. Set REFERENCE_CARS_DRIVE_ID or use --drive-id.')
    archive_path = Path(args.artifact).resolve()
    try:
        download_from_drive(file_id, archive_path)
    except Exception as exc:
        raise SystemExit(f'Failed to download reference pack: {exc}')
    extract_archive(archive_path, dest, force=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())

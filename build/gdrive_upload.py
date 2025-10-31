import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable"
FILES_URL = "https://www.googleapis.com/drive/v3/files"


def get_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        return payload["access_token"]


def start_resumable(access_token: str, name: str, size: int, folder_id: str | None) -> str:
    meta = {"name": name}
    if folder_id:
        meta["parents"] = [folder_id]
    body = json.dumps(meta).encode("utf-8")
    req = urllib.request.Request(UPLOAD_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json; charset=UTF-8")
    req.add_header("X-Upload-Content-Type", "application/octet-stream")
    req.add_header("X-Upload-Content-Length", str(size))
    with urllib.request.urlopen(req, timeout=30) as resp:
        upload_url = resp.headers.get("Location")
        if not upload_url:
            raise RuntimeError("Missing resumable upload Location header")
        return upload_url


def upload_chunks(upload_url: str, file_path: Path, chunk_size: int = 8 * 1024 * 1024) -> dict:
    total = file_path.stat().st_size
    sent = 0
    with open(file_path, "rb") as f:
        while sent < total:
            f.seek(sent)
            to_send = min(chunk_size, total - sent)
            data = f.read(to_send)
            start = sent
            end = sent + len(data) - 1
            req = urllib.request.Request(upload_url, data=data, method="PUT")
            req.add_header("Content-Length", str(len(data)))
            req.add_header("Content-Range", f"bytes {start}-{end}/{total}")
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    # Completed upload
                    payload = resp.read()
                    if payload:
                        return json.loads(payload.decode("utf-8", errors="replace"))
                    return {}
            except urllib.error.HTTPError as e:
                # 308 Resume Incomplete
                if e.code == 308:
                    rng = e.headers.get("Range")
                    if rng:
                        # Format: bytes=0-xxxxx
                        m = re.search(r"(\d+)$", rng)
                        if m:
                            sent = int(m.group(1)) + 1
                        else:
                            sent = end + 1
                    else:
                        sent = end + 1
                    continue
                else:
                    raise
    return {}


def set_public_anyone(access_token: str, file_id: str) -> None:
    url = f"{FILES_URL}/{urllib.parse.quote(file_id)}/permissions"
    req = urllib.request.Request(url, data=json.dumps({
        "role": "reader",
        "type": "anyone",
        "allowFileDiscovery": False,
    }).encode("utf-8"), method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30):
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload a file to Google Drive and output its public link.")
    ap.add_argument("--file", required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--folder", default=None, help="Destination folder id")
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--client-secret", required=True)
    ap.add_argument("--refresh-token", required=True)
    args = ap.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print("ERROR: file not found", file=sys.stderr)
        return 2
    name = args.name or file_path.name
    size = file_path.stat().st_size

    token = get_access_token(args.client_id, args.client_secret, args.refresh_token)
    upload_url = start_resumable(token, name, size, args.folder)
    info = upload_chunks(upload_url, file_path)
    file_id = info.get("id") if isinstance(info, dict) else None
    if not file_id:
        print("ERROR: upload failed", file=sys.stderr)
        return 3
    set_public_anyone(token, file_id)
    public_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    # Print key=value lines for easy parsing in batch
    print(f"FILE_ID={file_id}")
    print(f"PUBLIC_URL={public_url}")
    print(f"NAME={name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


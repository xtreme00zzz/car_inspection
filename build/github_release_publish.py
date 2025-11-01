import argparse
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


API = 'https://api.github.com'


def gh_headers(token: str, is_json: bool = True) -> dict:
    h = {
        'User-Agent': 'ef-scrutineer-release-publisher',
        'Authorization': f'Bearer {token}',
    }
    if is_json:
        h['Accept'] = 'application/vnd.github+json'
        h['Content-Type'] = 'application/json'
    return h


def http_json(url: str, token: str, method: str = 'GET', payload: dict | None = None) -> tuple[int, dict | list | None]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method=method, headers=gh_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if not raw:
                return resp.status, None
            return resp.status, json.loads(raw.decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as e:
        try:
            raw = e.read() if hasattr(e, 'read') else b''
            payload = json.loads(raw.decode('utf-8', errors='replace')) if raw else None
        except Exception:
            payload = None
        return e.code, payload


def ensure_release(owner: str, repo: str, tag: str, token: str, title: str, body: str) -> dict:
    status, payload = http_json(f'{API}/repos/{owner}/{repo}/releases/tags/{urllib.parse.quote(tag)}', token, 'GET')
    if status == 200 and isinstance(payload, dict):
        return payload
    # Create release
    create = {
        'tag_name': tag,
        'name': title,
        'body': body,
        'draft': False,
        'prerelease': False,
    }
    status, payload = http_json(f'{API}/repos/{owner}/{repo}/releases', token, 'POST', create)
    if status not in (200, 201) or not isinstance(payload, dict):
        raise SystemExit(f'Failed to create release {tag}: HTTP {status} {payload}')
    return payload

def list_assets(owner: str, repo: str, release_id: int, token: str) -> list[dict]:
    status, payload = http_json(f'{API}/repos/{owner}/{repo}/releases/{release_id}/assets', token, 'GET')
    return payload if isinstance(payload, list) else []

def delete_asset(owner: str, repo: str, asset_id: int, token: str) -> None:
    url = f'{API}/repos/{owner}/{repo}/releases/assets/{asset_id}'
    http_json(url, token, 'DELETE')


def upload_asset(upload_url: str, token: str, artifact_path: Path, content_type: str = 'application/octet-stream', as_name: str | None = None) -> None:
    # upload_url includes a template like {...}?name,label — strip template
    base = upload_url.split('{', 1)[0]
    name = as_name or artifact_path.name
    url = f'{base}?name={urllib.parse.quote(name)}'
    data = artifact_path.read_bytes()
    headers = gh_headers(token, is_json=False)
    headers['Content-Type'] = content_type
    headers['Content-Length'] = str(len(data))
    req = urllib.request.Request(url, data=data, method='POST', headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        if resp.status not in (200, 201):
            raise SystemExit(f'Asset upload failed: HTTP {resp.status}')


def main() -> int:
    ap = argparse.ArgumentParser(description='Publish/update GitHub Release and upload a small asset (manifest).')
    ap.add_argument('--owner', required=True)
    ap.add_argument('--repo', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--title', required=True)
    ap.add_argument('--body', default='')
    ap.add_argument('--asset', required=True, help='Path to asset file to upload (e.g., update.json)')
    ap.add_argument('--as-name', default=None, help='Override asset name when uploading')
    ap.add_argument('--token', default=None, help='GitHub token (optional; overrides env)')
    ap.add_argument('--clobber', action='store_true', help='Delete any existing asset with the same name before upload')
    args = ap.parse_args()

    token = args.token or (
        os.getenv('EF_SCRUTINEER_GITHUB_TOKEN')
        or os.getenv('GITHUB_TOKEN')
        or os.getenv('GH_TOKEN')
    )
    if not token:
        raise SystemExit('Missing GitHub token. Set EF_SCRUTINEER_GITHUB_TOKEN or GITHUB_TOKEN or GH_TOKEN')

    release = ensure_release(args.owner, args.repo, args.tag, token, args.title, args.body)
    upload_url = release.get('upload_url')
    if not upload_url:
        raise SystemExit('Release upload_url missing')
    artifact_path = Path(args.asset)
    if not artifact_path.exists():
        raise SystemExit(f'Asset not found: {artifact_path}')
    if args.clobber and 'id' in release:
        assets = list_assets(args.owner, args.repo, int(release['id']), token)
        target_name = args.as_name or artifact_path.name
        for a in assets:
            if a.get('name') == target_name and 'id' in a:
                delete_asset(args.owner, args.repo, int(a['id']), token)
                break
    content_type = 'application/json' if artifact_path.suffix.lower() == '.json' else 'application/octet-stream'
    upload_asset(upload_url, token, artifact_path, content_type=content_type, as_name=args.as_name)
    print(f'Uploaded asset {artifact_path} to release {args.tag}')
    return 0


if __name__ == '__main__':
    import os
    raise SystemExit(main())

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser(description='Generate update manifest JSON for external hosting (e.g., Cloudflare R2).')
    p.add_argument('--file', required=True, help='Path to installer/exe to publish')
    p.add_argument('--url', required=True, help='Public URL where the file will be downloadable')
    p.add_argument('--out', required=True, help='Output manifest JSON path')
    p.add_argument('--name', default=None, help='Override artifact name in manifest')
    args = p.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        raise SystemExit(f'File not found: {file_path}')
    size = file_path.stat().st_size
    digest = sha256_file(file_path)
    name = args.name or file_path.name

    manifest = {
        'name': name,
        'url': args.url,
        'size': size,
        'sha256': digest,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Wrote manifest to {out_path} (size={size}, sha256={digest})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

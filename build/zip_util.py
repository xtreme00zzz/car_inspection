import argparse
import zipfile
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description='Create a zip archive from a single file.')
    ap.add_argument('--src', required=True, help='Source file to add')
    ap.add_argument('--dst', required=True, help='Destination .zip path')
    args = ap.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)
    if not src.exists():
        print(f'ERROR: source not found: {src}')
        return 2
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(src, arcname=src.name)
    print(dst.resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


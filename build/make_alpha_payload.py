from __future__ import annotations

import shutil
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    dist_dir = root / "dist"
    onedir = dist_dir / "car_inspection_alpha"
    onefile = dist_dir / "car_inspection_alpha.exe"
    payload_name = sys.argv[1] if len(sys.argv) > 1 else "alpha_payload"
    payload = dist_dir / payload_name
    docs_dir = payload / "docs"

    print(f"Building payload '{payload_name}'")

    if not onedir.exists():
        raise SystemExit(f"Onedir build missing at {onedir}")
    if not onefile.exists():
        raise SystemExit(f"Onefile executable missing at {onefile}")

    if payload.exists():
        print(f"  removing existing payload folder: {payload}")
        try:
            shutil.rmtree(payload)
        except PermissionError:
            backup = payload.with_suffix("_old")
            counter = 1
            while backup.exists():
                counter += 1
                backup = payload.with_suffix(f"_old{counter}")
            print(f"  unable to remove, renaming to {backup}")
            payload.rename(backup)
    payload.mkdir(parents=True, exist_ok=True)

    print("  copying onedir -> payload/app ...")
    shutil.copytree(onedir, payload / "app")

    print("  copying onefile executable ...")
    shutil.copy2(onefile, payload / "car_inspection_alpha.exe")

    print("  copying docs ...")
    docs_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "build" / "alpha_release_notes.txt", docs_dir / "alpha_release_notes.txt")
    shutil.copy2(root / "README.md", docs_dir / "README.md")

    (payload / "VERSION.txt").write_text("eF Drift Car Scrutineer ALPHA-0.1.0\n", encoding="utf-8")
    print("  payload ready")


if __name__ == "__main__":
    main()

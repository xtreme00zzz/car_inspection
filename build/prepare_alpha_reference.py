#!/usr/bin/env python3
"""
Create a trimmed copy of the reference car assets for packaging.

The validator only needs the physics data (data/, extension/, collider.kn5, etc.)
and the directory/file names at the root level. Large assets such as car.kn5
models, textures, and audio banks unnecessarily inflate the installer and can
trigger corruption errors during extraction. This script copies the minimal set
of files required for validation while preserving the expected directory names.
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path
from typing import Callable

ROOT_COPY_EXTS = {".ini", ".json", ".txt", ".cfg", ".md", ".acd", ".lut"}
SKIN_COPY_EXTS = {".ini", ".json", ".txt"}
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = REPO_ROOT / "reference_cars"
DEFAULT_DEST = REPO_ROOT / "build" / "reference_cars_alpha"


def copy_tree_filtered(src: Path, dest: Path, predicate: Callable[[Path], bool] | None = None) -> None:
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        target_dir = dest / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname in files:
            src_file = Path(root) / fname
            if predicate and not predicate(src_file):
                continue
            shutil.copy2(src_file, target_dir / fname)


def write_placeholder(path: Path, original: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    placeholder = (
        "Trimmed placeholder generated during packaging.\n"
        f"Original file: {original.name} ({original.stat().st_size} bytes)\n"
        "The full asset is not required for validation at runtime.\n"
    )
    path.write_text(placeholder, encoding="utf-8")


def trim_car(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)

    for entry in sorted(src.iterdir()):
        if entry.is_dir():
            name = entry.name.lower()
            if name in {"data", "extension", "ui"}:
                shutil.copytree(entry, dest / entry.name, dirs_exist_ok=True)
            elif name == "skins":
                skins_dest = dest / entry.name
                skins_dest.mkdir(exist_ok=True)
                for skin in sorted(entry.iterdir()):
                    if not skin.is_dir():
                        continue
                    skin_dest = skins_dest / skin.name
                    skin_dest.mkdir(parents=True, exist_ok=True)

                    def allow_skin_file(p: Path) -> bool:
                        return p.suffix.lower() in SKIN_COPY_EXTS

                    copy_tree_filtered(skin, skin_dest, predicate=allow_skin_file)
            else:
                # Preserve directory name without heavy assets inside.
                (dest / entry.name).mkdir(exist_ok=True)
        elif entry.is_file():
            name = entry.name.lower()
            suffix = Path(name).suffix.lower()
            dest_path = dest / entry.name

            if name == "collider.kn5":
                shutil.copy2(entry, dest_path)
            elif suffix in ROOT_COPY_EXTS:
                shutil.copy2(entry, dest_path)
            elif suffix == ".kn5":
                write_placeholder(dest_path, entry)
            elif entry.stat().st_size <= 2 * 1024 * 1024:
                # Copy smaller miscellaneous files (<2 MB) to be safe.
                shutil.copy2(entry, dest_path)
            else:
                write_placeholder(dest_path, entry)


def build_trimmed_reference(src_root: Path, dest_root: Path) -> None:
    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)

    for car_dir in sorted(src_root.iterdir()):
        if car_dir.is_dir():
            trim_car(car_dir, dest_root / car_dir.name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare trimmed reference assets for packaging.")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="Source reference cars directory.")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="Destination trimmed output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    src = args.src.resolve()
    dest = args.dest.resolve()

    if not src.exists():
        raise SystemExit(f"Source reference directory not found: {src}")

    build_trimmed_reference(src, dest)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def load_app_icon(repo_root: Path) -> Image.Image | None:
    ico = repo_root / "icon.ico"
    if not ico.exists():
        return None
    try:
        img = Image.open(ico)
        # Select the largest size from the multi-resolution .ico
        frames = []
        try:
            i = 0
            while True:
                img.seek(i)
                frames.append(img.copy())
                i += 1
        except EOFError:
            pass
        if frames:
            frames.sort(key=lambda im: im.width * im.height, reverse=True)
            return frames[0].convert("RGBA")
        return img.convert("RGBA")
    except Exception:
        return None


def solid(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", size, color)


def draw_text_centered(img: Image.Image, text: str, y: int, color: tuple[int, int, int] = (255, 255, 255)) -> None:
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
    try:
        left, top, right, bottom = d.textbbox((0, 0), text, font=font)
        tw, th = right - left, bottom - top
    except Exception:
        # Fallback for older Pillow
        try:
            tw, th = d.textsize(text, font=font)
        except Exception:
            tw, th = len(text) * 8, 12
    x = max(0, (img.width - tw) // 2)
    d.text((x, y), text, fill=color, font=font)


def make_wizard(repo_root: Path, out_dir: Path) -> None:
    ensure_dir(out_dir)
    # Inno large wizard image: 164x314 (24-bit BMP)
    # Solid black background to match logo styling
    canvas = solid((164, 314), (0, 0, 0))
    icon = load_app_icon(repo_root)
    if icon is not None:
        # Paste icon scaled nicely
        target_w = 120
        scale = target_w / icon.width
        target_h = int(icon.height * scale)
        icon_resized = icon.resize((target_w, target_h), Image.LANCZOS)
        x = (canvas.width - target_w) // 2
        y = 36
        canvas.paste(icon_resized, (x, y), icon_resized)
    # Branding text in white, lowered to avoid overlaps
    draw_text_centered(canvas, "eF Drift", 14, (255, 255, 255))
    draw_text_centered(canvas, "Car Scrutineer", 32, (255, 255, 255))
    draw_text_centered(canvas, "Alpha", 52, (200, 200, 200))
    # Subtle bottom divider
    d = ImageDraw.Draw(canvas)
    d.line([10, canvas.height - 22, canvas.width - 10, canvas.height - 22], fill=(40, 40, 40), width=1)
    # Save as 24-bit BMP
    out = out_dir / "wizard.bmp"
    canvas.convert("RGB").save(out, format="BMP")


def make_wizard_small(repo_root: Path, out_dir: Path) -> None:
    ensure_dir(out_dir)
    # Inno small wizard image: 55x55 (24-bit BMP)
    # Solid black to ensure the header icon has a black background
    canvas = solid((55, 55), (0, 0, 0))
    icon = load_app_icon(repo_root)
    if icon is not None:
        # Fit into 40x40
        target = 40
        scale = min(target / icon.width, target / icon.height)
        icon_resized = icon.resize((max(1, int(icon.width * scale)), max(1, int(icon.height * scale))), Image.LANCZOS)
        x = (55 - icon_resized.width) // 2
        y = (55 - icon_resized.height) // 2
        canvas.paste(icon_resized, (x, y), icon_resized)
    else:
        d = ImageDraw.Draw(canvas)
        d.ellipse([8, 8, 47, 47], outline=(120, 160, 255), width=2)
    out = out_dir / "wizard_small.bmp"
    canvas.convert("RGB").save(out, format="BMP")


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    out_dir = repo_root / "build" / "branding"
    make_wizard(repo_root, out_dir)
    make_wizard_small(repo_root, out_dir)
    print(f"Branding assets generated in {out_dir}")


if __name__ == "__main__":
    main()

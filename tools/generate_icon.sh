#!/usr/bin/env bash
set -euo pipefail

# Simple deterministic icon generator using ImageMagick.
# Produces a square EFVD-branded icon with multiple resolutions.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}"
PREVIEW="${OUT_DIR}/icon_preview.png"
ICON="${OUT_DIR}/icon.ico"

if ! command -v convert >/dev/null 2>&1; then
  echo "ImageMagick 'convert' command is required." >&2
  exit 1
fi

convert -size 512x512 xc:"#10316B" \
  -stroke "#E25822" -strokewidth 22 -fill none -draw "roundrectangle 42,42 470,470 110,110" \
  -fill "#F4F4F4" -stroke none \
  -draw "roundrectangle 140,150 210,360 20,20" \
  -draw "roundrectangle 210,150 360,198 20,20" \
  -draw "roundrectangle 210,248 320,296 20,20" \
  -draw "roundrectangle 210,312 360,360 20,20" \
  -fill "#E25822" \
  -draw "roundrectangle 300,150 370,360 20,20" \
  -draw "roundrectangle 370,150 460,198 20,20" \
  -draw "roundrectangle 370,248 450,296 20,20" \
  "${PREVIEW}"

convert "${PREVIEW}" -define icon:auto-resize=256,128,64,48,32,24,16 "${ICON}"

echo "Generated ${ICON} (preview at ${PREVIEW})"

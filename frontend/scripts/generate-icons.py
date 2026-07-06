#!/usr/bin/env python3
"""Generate PNG app icons matching public/favicon.svg."""

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "public"
SIZES = {
    "apple-touch-icon.png": 180,
    "icon-192.png": 192,
    "icon-512.png": 512,
}

BG = (255, 248, 225)
RAY_LARGE = (255, 193, 7)
RAY_SMALL = (255, 213, 79)
CORE_INNER = (255, 241, 118)
CORE_MID = (255, 214, 0)
CORE_OUTER = (255, 179, 0)
CORE_STROKE = (255, 143, 0, 90)


def rotate_point(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return x * cos_a - y * sin_a, x * sin_a + y * cos_a


def triangle(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float, angle: float, color):
    points = [(0, -38 * scale), (7 * scale, -18 * scale), (-7 * scale, -18 * scale)]
    rotated = [rotate_point(x, y, angle) for x, y in points]
    draw.polygon([(cx + x, cy + y) for x, y in rotated], fill=color)


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG + (255,))
    draw = ImageDraw.Draw(img, "RGBA")
    scale = size / 100
    cx = cy = size / 2
    radius = int(18 * scale)

    for angle in (0, 90, 180, 270):
        triangle(draw, cx, cy, scale, angle, RAY_LARGE)
    for angle in (45, 135, 225, 315):
        small_scale = scale * 0.72
        points = [(27 * small_scale, -27 * small_scale), (32 * small_scale, -14 * small_scale), (20 * small_scale, -20 * small_scale)]
        rotated = [rotate_point(x, y, angle) for x, y in points]
        draw.polygon([(cx + x, cy + y) for x, y in rotated], fill=RAY_SMALL)

    core_r = int(17 * scale)
    for i, color in enumerate((CORE_OUTER, CORE_MID, CORE_INNER)):
        r = core_r - i * max(1, int(2.5 * scale))
        offset = int((2 - i) * scale)
        bbox = (cx - r + offset, cy - r - offset, cx + r + offset, cy + r - offset)
        draw.ellipse(bbox, fill=color)

    stroke_r = core_r
    draw.ellipse(
        (cx - stroke_r, cy - stroke_r, cx + stroke_r, cy + stroke_r),
        outline=CORE_STROKE,
        width=max(1, int(1.2 * scale)),
    )
    return img


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, size in SIZES.items():
        draw_icon(size).save(OUT_DIR / filename, format="PNG")
        print(f"Wrote {OUT_DIR / filename}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate application icon programmatically using Pillow.

Design: A stylized document with a downward arrow and a subtle medical cross,
representing clinical trial document downloading. Primary color: #3B82F6 (blue).

Run: python assets/generate_icon.py
Outputs: assets/icon.ico, assets/icon.png
"""

import os
import math

from PIL import Image, ImageDraw

# Colors
PRIMARY = (59, 130, 246)       # #3B82F6
PRIMARY_DARK = (37, 99, 235)   # #2563EB
WHITE = (255, 255, 255)
LIGHT_BLUE = (147, 197, 253)   # #93C5FD
VERY_LIGHT = (219, 234, 254)   # #DBEAFE


def draw_icon(size: int) -> Image.Image:
    """Draw the application icon at the given pixel size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Scale factor relative to 256x256 master
    s = size / 256.0

    # -- Rounded rectangle background --
    margin = int(10 * s)
    corner = int(40 * s)
    bg_bbox = [margin, margin, size - margin, size - margin]
    draw.rounded_rectangle(bg_bbox, radius=corner, fill=PRIMARY)

    # -- Inner highlight (subtle gradient effect) --
    inner_margin = int(16 * s)
    inner_corner = int(32 * s)
    inner_bbox = [inner_margin, inner_margin, size - inner_margin, size - inner_margin]
    draw.rounded_rectangle(inner_bbox, radius=inner_corner, fill=PRIMARY_DARK)

    # Re-draw main background to create subtle border effect
    bg_margin2 = int(12 * s)
    bg_corner2 = int(38 * s)
    bg_bbox2 = [bg_margin2, bg_margin2, size - bg_margin2, size - bg_margin2]
    draw.rounded_rectangle(bg_bbox2, radius=bg_corner2, fill=PRIMARY)

    # -- Document shape (upper-left area) --
    doc_left = int(52 * s)
    doc_top = int(40 * s)
    doc_right = int(148 * s)
    doc_bottom = int(180 * s)
    doc_corner = int(8 * s)

    # Document body
    draw.rounded_rectangle(
        [doc_left, doc_top, doc_right, doc_bottom],
        radius=doc_corner,
        fill=WHITE,
    )

    # Document fold (top-right corner)
    fold_size = int(24 * s)
    fold_points = [
        (doc_right - fold_size, doc_top),
        (doc_right, doc_top + fold_size),
        (doc_right - fold_size, doc_top + fold_size),
    ]
    draw.polygon(fold_points, fill=VERY_LIGHT)

    # -- Text lines on document --
    line_color = LIGHT_BLUE
    line_h = int(6 * s)
    line_gap = int(18 * s)
    line_left = int(66 * s)
    line_right = int(132 * s)

    for i, (lw_factor, ltop) in enumerate([
        (1.0, int(72 * s)),
        (0.8, int(72 * s) + line_gap),
        (0.6, int(72 * s) + line_gap * 2),
        (0.9, int(72 * s) + line_gap * 3),
        (0.7, int(72 * s) + line_gap * 4),
    ]):
        lr = int(line_left + (line_right - line_left) * lw_factor)
        draw.rounded_rectangle(
            [line_left, ltop, lr, ltop + line_h],
            radius=int(3 * s),
            fill=line_color,
        )

    # -- Medical cross (lower-left of document) --
    cross_cx = int(100 * s)
    cross_cy = int(162 * s)
    cross_arm = int(18 * s)
    cross_thick = int(7 * s)

    # Horizontal bar
    draw.rounded_rectangle(
        [cross_cx - cross_arm, cross_cy - cross_thick // 2,
         cross_cx + cross_arm, cross_cy + cross_thick // 2],
        radius=int(2 * s),
        fill=PRIMARY,
    )
    # Vertical bar
    draw.rounded_rectangle(
        [cross_cx - cross_thick // 2, cross_cy - cross_arm,
         cross_cx + cross_thick // 2, cross_cy + cross_arm],
        radius=int(2 * s),
        fill=PRIMARY,
    )

    # -- Download arrow (right side) --
    arrow_cx = int(192 * s)
    arrow_top = int(56 * s)
    arrow_bottom = int(156 * s)
    arrow_w = int(14 * s)
    arrow_head = int(24 * s)

    # Arrow shaft
    shaft_left = arrow_cx - arrow_w // 2
    shaft_right = arrow_cx + arrow_w // 2
    draw.rounded_rectangle(
        [shaft_left, arrow_top, shaft_right, arrow_bottom - arrow_head // 2],
        radius=int(4 * s),
        fill=WHITE,
    )

    # Arrow head (triangle pointing down)
    head_points = [
        (arrow_cx - arrow_head, arrow_bottom - arrow_head),
        (arrow_cx + arrow_head, arrow_bottom - arrow_head),
        (arrow_cx, arrow_bottom),
    ]
    draw.polygon(head_points, fill=WHITE)

    # -- Small data dots (decorative) --
    dots = [
        (int(175 * s), int(174 * s)),
        (int(195 * s), int(180 * s)),
        (int(210 * s), int(172 * s)),
    ]
    for dx, dy in dots:
        r = int(4 * s)
        draw.ellipse([dx - r, dy - r, dx + r, dy + r], fill=LIGHT_BLUE)

    return img


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = script_dir

    # Generate master at 256x256
    master = draw_icon(256)

    # Save PNG
    png_path = os.path.join(output_dir, "icon.png")
    master.save(png_path, "PNG")
    print(f"Created: {png_path}")

    # Save ICO with multiple sizes
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    ico_images = []
    for sz in ico_sizes:
        ico_images.append(draw_icon(sz))

    ico_path = os.path.join(output_dir, "icon.ico")
    # PIL ICO: pass the largest image, it will generate all sizes
    master.save(
        ico_path,
        format="ICO",
        sizes=[(sz, sz) for sz in ico_sizes],
        append_images=ico_images,
    )
    print(f"Created: {ico_path}")
    print("Icon generation complete.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Bake sticker-style 'Sprunki Pokémon Jam' title into intro preview art.

Reads art/intro-preview-gray-simon-pinki.png (or --base), nudges characters down,
draws two-line rainbow sticker title inside the stage-visible safe zone, writes
art + /workspace/intro-preview-check.png (+ top crop for verification).

Stage safe-zone (critical):
  Master art is 1280×960 with bitmapResolution=2 → 640×480 costume units.
  Scratch/TurboWarp stage is 480×360. Costume is centered on stage, so
  ~60 costume units (120 image px) are clipped at top AND bottom (and
  ~80 costume units / 160 image px left AND right).
  Visible image region when centered:
    X ≈ 160..1120
    Y ≈ 120..840
  Title must stay fully inside Y≈120..840 (and preferably clear of heads).
  Do NOT re-bake on already-titled art (double text) — pass a clean untitled
  base via --base (e.g. git show 0120bb9:art/intro-preview-gray-simon-pinki.png).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ART = ROOT / "art" / "intro-preview-gray-simon-pinki.png"
CHECK = Path("/workspace/intro-preview-check.png")
SAFE_CHECK = Path("/workspace/intro-title-safe-check.png")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
W, H = 1280, 960
# Nudge characters down so lowered title (safe-zone) clears Gray's head.
SHIFT = 80

RAINBOW = [
    (255, 110, 30),
    (255, 210, 40),
    (255, 80, 170),
    (60, 220, 255),
    (120, 255, 70),
    (200, 110, 255),
    (255, 150, 50),
]


def draw_sticker_line(
    base: Image.Image,
    text: str,
    cy: int,
    font_size: int,
    colors: list,
    letter_spacing: int = 5,
) -> Image.Image:
    font = ImageFont.truetype(FONT, font_size)
    widths = []
    for ch in text:
        b = font.getbbox(ch)
        widths.append(b[2] - b[0] if ch != " " else max(font_size // 3, 18))
    total = sum(widths) + letter_spacing * max(0, len(text) - 1)
    x0 = (W - total) / 2.0
    ascent, _ = font.getmetrics()
    y = cy - ascent // 2

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    outline_black = max(7, font_size // 11)
    outline_white = max(4, font_size // 18)

    x = x0
    ci = 0
    for i, ch in enumerate(text):
        if ch == " ":
            x += widths[i] + letter_spacing
            continue
        color = colors[ci % len(colors)]
        ci += 1
        for dx in range(-outline_black, outline_black + 1):
            for dy in range(-outline_black, outline_black + 1):
                if dx * dx + dy * dy <= outline_black * outline_black:
                    ld.text((x + dx, y + dy), ch, font=font, fill=(15, 8, 25, 255))
        for dx in range(-outline_white, outline_white + 1):
            for dy in range(-outline_white, outline_white + 1):
                if dx * dx + dy * dy <= outline_white * outline_white:
                    ld.text((x + dx, y + dy), ch, font=font, fill=(255, 255, 255, 255))
        ld.text((x, y), ch, font=font, fill=(*color, 255))
        x += widths[i] + letter_spacing

    alpha = layer.split()[-1]
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(alpha.point(lambda p: int(p * 0.45)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(5))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(shadow, (4, 6), shadow)
    out = Image.alpha_composite(out, layer)
    return Image.alpha_composite(base, out)


def bake(base_path: Path, art_path: Path, check_path: Path) -> None:
    im = Image.open(base_path).convert("RGBA")
    if im.size != (W, H):
        raise SystemExit(f"expected {W}x{H}, got {im.size}")
    # Sample bg from corner and shift characters down
    bg = im.getpixel((8, 8))
    shifted = Image.new("RGBA", (W, H), bg)
    shifted.paste(im.crop((0, 0, W, H - SHIFT)), (0, SHIFT))
    im = shifted

    # Title inside stage-visible Y≈120..840 (cy≈200 / 290 clears clip + heads).
    im = draw_sticker_line(im, "SPRUNKI", 200, 84, RAINBOW, letter_spacing=8)
    im = draw_sticker_line(
        im, "Pokémon Jam", 290, 64, RAINBOW[2:] + RAINBOW[:2], letter_spacing=5
    )
    art_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(art_path, "PNG", optimize=True)
    check_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(check_path, "PNG", optimize=True)
    # Top crop for quick safe-zone verification (includes Y=120 clip line).
    im.crop((0, 0, W, 400)).save(SAFE_CHECK, "PNG", optimize=True)
    print(f"wrote {art_path} ({art_path.stat().st_size} bytes)")
    print(f"wrote {check_path}")
    print(f"wrote {SAFE_CHECK}")
    print(f"safe-zone: visible Y≈120..840; title cy=200/290 SHIFT={SHIFT}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--base",
        type=Path,
        default=None,
        help="Untitled source PNG (default: current art file, or git HEAD if --from-git)",
    )
    ap.add_argument("--from-git", action="store_true", help="Use git HEAD art as base")
    args = ap.parse_args()
    if args.from_git:
        import subprocess
        import tempfile

        blob = subprocess.check_output(
            ["git", "show", "HEAD:art/intro-preview-gray-simon-pinki.png"],
            cwd=ROOT,
        )
        tmp = Path(tempfile.mkstemp(suffix=".png")[1])
        tmp.write_bytes(blob)
        base = tmp
    else:
        base = args.base or DEFAULT_ART
    bake(base, DEFAULT_ART, CHECK)


if __name__ == "__main__":
    main()

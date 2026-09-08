#!/usr/bin/env python3
"""Replace holey Gray in intro lineup with fixed gray-phase1, then re-bake title.

Rebuilds Simon | Gray | Pinki on a dark-blue radial from current phase1 sprites
(same approach as a8e30a4 /tmp/rebuild_intro.py), so Gray gets solid interiors
+ soft fringe without leaving erase artifacts from the old baked composite.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bake_intro_title import bake  # noqa: E402

W, H = 1280, 960
INTRO = ROOT / "art" / "intro-preview-gray-simon-pinki.png"
OUT_UNTITLED = Path("/tmp/intro-gray-replaced-pre-title.png")
CHECK = Path("/workspace/intro-preview-check.png")


def radial_dark_blue(size=(W, H)) -> Image.Image:
    """Deep navy radial: center #1a2a4a → edge #070b18."""
    w, h = size
    cx, cy = w / 2, h / 2
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    r = r / r.max()
    c0 = np.array([0x1A, 0x2A, 0x4A], dtype=np.float32)  # #1a2a4a
    c1 = np.array([0x07, 0x0B, 0x18], dtype=np.float32)  # #070b18
    rgb = c0[None, None, :] * (1 - r[..., None]) + c1[None, None, :] * r[..., None]
    arr = np.clip(rgb, 0, 255).astype(np.uint8)
    a = np.full((h, w, 1), 255, dtype=np.uint8)
    return Image.fromarray(np.concatenate([arr, a], axis=2), "RGBA")


def place(canvas: Image.Image, sprite: Image.Image, cx: int, cy: int, target_h: int) -> None:
    scale = target_h / sprite.height
    nw = max(1, int(round(sprite.width * scale)))
    sp = sprite.resize((nw, target_h), Image.Resampling.LANCZOS)
    x = int(cx - nw / 2)
    y = int(cy - target_h / 2)
    canvas.alpha_composite(sp, (x, y))
    print(f"place {sprite.size} -> {(nw, target_h)} at paste=({x},{y}) center=({cx},{cy})")


def main() -> None:
    simon = Image.open(ROOT / "art/simon-phase1.png").convert("RGBA")
    gray = Image.open(ROOT / "art/gray-phase1.png").convert("RGBA")
    pinki = Image.open(ROOT / "art/pinki-phase1.png").convert("RGBA")
    print("sprites", simon.size, gray.size, pinki.size)

    canvas = radial_dark_blue()
    # Layout tuned for stage-visible area after SHIFT=80 in bake.
    # Gray centered behind DJ deck; Simon left / Pinki right.
    place(canvas, simon, cx=220, cy=520, target_h=520)
    place(canvas, pinki, cx=1060, cy=540, target_h=480)
    place(canvas, gray, cx=640, cy=560, target_h=620)

    canvas.save(OUT_UNTITLED)
    print("wrote", OUT_UNTITLED)

    bake(OUT_UNTITLED, INTRO, CHECK)
    print("rebaked intro", INTRO, INTRO.stat().st_size)


if __name__ == "__main__":
    main()

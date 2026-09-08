#!/usr/bin/env python3
"""Rebuild custom-character anim costumes as vertically shifted bounce frames.

Root cause of missing beat bounce: embeds stamped the same Phase1 PNG onto idle
and every anim* (and Phase2 onto every anim???*), so costume cycling showed no
motion. This script keeps idle/idle2/b3 at offset 0 and writes unique PNGs for
anim frames with a bounce pattern.

Clipping fix: expand each phase canvas with transparent top+bottom padding
(>= max |offset| + EXTRA_PAD_PX) before shifting, so upward bounce never chops
the sprite top. Base art is centered in the padded canvas; bounce is a vertical
translate within that canvas. rotationCenter is the padded-canvas center
(classic Sprunki whole-body bob).

Reusable: import apply_bounce_to_sb3() / pad_and_shift() from future embed scripts,
or run as CLI:

    python3 scripts/apply_bounce_frames.py
    python3 scripts/apply_bounce_frames.py --sb3 path/to.sb3
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_bg_pipeline import fill_interior_alpha_holes  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SB3 = ROOT / "sprunki-base.sb3"
ART = ROOT / "art"

# Positive = content shifted UP in the bitmap (bounce). Slightly softer than 16px.
BOUNCE_OFFSETS = (0, 4, 8, 10, 8, 4, 0, -3)
# Transparent headroom beyond max |offset| on top and bottom.
EXTRA_PAD_PX = 4

# art stem (art/<stem>-phase1.png) → Scratch sprite name
ART_TO_SPRITE: dict[str, str] = {
    "oren": "Orange (Oren)",
    "raddy": "Red (Raddy)",
    "vineria": "Green (Vineria)",
    "durple": "Purple (Durple)",
    "simon": "Yellow (Simon)",
    "pinki": "Pink (Pinki)",
    "sky": "Sky blue (Sky)",
    "mrsun": "Mr. Sun",
    "mrblack": "Black?",
    "mr-tree": "Mr. Tree",
    "jevin": "Blue (Jevin)",
    "funbot": "Fun Bot",
    "mrfuncomputer": "Mr. Fun Computer",
    "wenda": "White (Wenda)",
    "tunner": "Tan (Tunner)",
    "brud": "Brown (brud)",
    "clukr": "Silver (Clukr)",
    "gray": "Gray (Gray)",
    "owakcx": "Lime (OWAKCX)",
    "garnold": "Gold (Garnold)",
}


def png_md5(blob: bytes) -> tuple[str, str]:
    md5 = hashlib.md5(blob).hexdigest()
    return md5, f"{md5}.png"


def png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def bounce_pad(offsets: tuple[int, ...] = BOUNCE_OFFSETS) -> int:
    """Transparent px added to top and bottom (>= max |offset| + EXTRA_PAD_PX)."""
    return max(abs(o) for o in offsets) + EXTRA_PAD_PX


def pad_and_shift(im: Image.Image, dy: int, pad: int) -> Image.Image:
    """Center im in a canvas with `pad` transparent px top+bottom, then shift.

    Positive dy moves content UP within the padded canvas (no clipping when
    pad >= |dy|). Same width; height becomes h + 2*pad.
    """
    w, h = im.size
    out = Image.new("RGBA", (w, h + 2 * pad), (0, 0, 0, 0))
    # paste y = pad - dy → positive dy lifts content; pad absorbs the shift.
    # Do NOT pass `im` as mask: RGBA-as-mask multiplies alpha (soft fringe a→a²/255).
    out.paste(im, (0, pad - dy))
    return fill_interior_alpha_holes(out)


def shift_png(im: Image.Image, dy: int, pad: int | None = None) -> Image.Image:
    """Back-compat wrapper: pad-and-shift with default bounce pad."""
    if pad is None:
        pad = bounce_pad()
    return pad_and_shift(im, dy, pad)


def set_costume_png(c: dict, md5: str, md5ext: str, cx: float, cy: float) -> None:
    c["assetId"] = md5
    c["md5ext"] = md5ext
    c["dataFormat"] = "png"
    c["bitmapResolution"] = 2
    c["rotationCenterX"] = cx
    c["rotationCenterY"] = cy


def is_phase1_anim(name: str) -> bool:
    return name.startswith("anim") and "???" not in name


def is_phase2_anim(name: str) -> bool:
    return "???" in name


def apply_bounce_to_target(
    target: dict,
    phase1: Image.Image,
    phase2: Image.Image | None,
    assets: dict[str, bytes],
    offsets: tuple[int, ...] = BOUNCE_OFFSETS,
) -> dict[str, int]:
    """Stamp bounce frames onto one sprite. Returns counts."""
    pad = bounce_pad(offsets)

    # Idle / offset-0 frames use the same padded canvas as bounced anims so
    # costume size and rotationCenter stay stable across the bounce cycle.
    base1 = pad_and_shift(phase1, 0, pad)
    w1, h1 = base1.size
    cx1, cy1 = w1 / 2.0, h1 / 2.0
    blob1 = png_bytes(base1)
    md1, ext1 = png_md5(blob1)
    assets[ext1] = blob1

    md2 = ext2 = None
    cx2 = cy2 = None
    if phase2 is not None:
        base2 = pad_and_shift(phase2, 0, pad)
        w2, h2 = base2.size
        cx2, cy2 = w2 / 2.0, h2 / 2.0
        blob2 = png_bytes(base2)
        md2, ext2 = png_md5(blob2)
        assets[ext2] = blob2

    # Cache shifted frames by (phase, dy) so shared offsets reuse one asset
    cache: dict[tuple[str, int], tuple[str, str]] = {("p1", 0): (md1, ext1)}
    if md2 is not None:
        cache[("p2", 0)] = (md2, ext2)

    def frame(phase: str, dy: int, src: Image.Image) -> tuple[str, str]:
        key = (phase, dy)
        if key in cache:
            return cache[key]
        blob = png_bytes(pad_and_shift(src, dy, pad))
        md, ext = png_md5(blob)
        assets[ext] = blob
        cache[key] = (md, ext)
        return md, ext

    p1_anims = [c for c in target["costumes"] if is_phase1_anim(c["name"])]
    p2_anims = [c for c in target["costumes"] if is_phase2_anim(c["name"])]
    stats = {"idle": 0, "p1_anim": 0, "b3": 0, "p2_anim": 0, "other": 0, "pad": pad}

    for c in target["costumes"]:
        name = c["name"]
        if name in ("idle", "idle2"):
            set_costume_png(c, md1, ext1, cx1, cy1)
            stats["idle"] += 1
        elif name == "b3" and md2 is not None:
            set_costume_png(c, md2, ext2, cx2, cy2)
            stats["b3"] += 1
        elif is_phase1_anim(name):
            idx = p1_anims.index(c)
            dy = offsets[idx % len(offsets)]
            md, ext = frame("p1", dy, phase1)
            set_costume_png(c, md, ext, cx1, cy1)
            stats["p1_anim"] += 1
        elif is_phase2_anim(name) and phase2 is not None:
            idx = p2_anims.index(c)
            dy = offsets[idx % len(offsets)]
            md, ext = frame("p2", dy, phase2)
            set_costume_png(c, md, ext, cx2, cy2)
            stats["p2_anim"] += 1
        else:
            stats["other"] += 1

    return stats


def discover_art_chars() -> list[str]:
    stems = []
    for p in sorted(ART.glob("*-phase1.png")):
        stem = p.name[: -len("-phase1.png")]
        if stem in ART_TO_SPRITE:
            stems.append(stem)
        else:
            print(f"  WARN: no sprite mapping for art/{p.name}, skip")
    return stems


def apply_bounce_to_sb3(
    sb3_path: Path,
    offsets: tuple[int, ...] = BOUNCE_OFFSETS,
    chars: list[str] | None = None,
) -> None:
    stems = chars or discover_art_chars()
    with zipfile.ZipFile(sb3_path, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    by_name = {t["name"]: t for t in data["targets"]}
    pad = bounce_pad(offsets)
    print(f"bounce offsets: {offsets}  pad_top/bottom: {pad}px")
    for stem in stems:
        sprite = ART_TO_SPRITE[stem]
        p1_path = ART / f"{stem}-phase1.png"
        p2_path = ART / f"{stem}-phase2.png"
        if sprite not in by_name:
            print(f"  SKIP {stem}: sprite {sprite!r} missing")
            continue
        phase1 = Image.open(p1_path).convert("RGBA")
        phase2 = Image.open(p2_path).convert("RGBA") if p2_path.is_file() else None
        stats = apply_bounce_to_target(
            by_name[sprite], phase1, phase2, assets, offsets=offsets
        )
        p2n = phase2.size if phase2 else None
        print(
            f"  {sprite}: p1={phase1.size}->{(phase1.size[0], phase1.size[1]+2*pad)} "
            f"p2={p2n} "
            f"idle={stats['idle']} anim={stats['p1_anim']} "
            f"b3={stats['b3']} ???={stats['p2_anim']} other={stats['other']}"
        )

    used: set[str] = set()
    for t in data["targets"]:
        for c in t.get("costumes", []):
            if c.get("md5ext"):
                used.add(c["md5ext"])
        for s in t.get("sounds", []):
            if s.get("md5ext"):
                used.add(s["md5ext"])
    new_assets = {k: v for k, v in assets.items() if k in used}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(data, separators=(",", ":")))
        for name, blob in sorted(new_assets.items()):
            z.writestr(name, blob)
    sb3_path.write_bytes(buf.getvalue())
    print(f"wrote {sb3_path} ({sb3_path.stat().st_size} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sb3", type=Path, default=DEFAULT_SB3)
    ap.add_argument(
        "--chars",
        nargs="*",
        default=None,
        help="Optional art stems (default: all with phase1 art + mapping)",
    )
    args = ap.parse_args()
    apply_bounce_to_sb3(args.sb3, chars=args.chars)


if __name__ == "__main__":
    main()

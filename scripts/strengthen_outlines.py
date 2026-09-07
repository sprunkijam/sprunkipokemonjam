#!/usr/bin/env python3
"""Strengthen black outlines on custom Sprunki art; remake face icons; re-embed sb3.

Default mode is heavy_wide (~4–6px Polo-weight stroke on ~400px art).
Never re-process Oren — leave art/oren-* and Oren costumes alone.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "art"
SB3 = ROOT / "sprunki-base.sb3"
PREVIEW = ART / "_preview"

# Skip entirely — Oren outline is already correct.
SKIP_CHARS = frozenset({"oren"})

# Characters touched by this pass (phase1+2 art + icons).
TARGET_CHARS = ("raddy", "vineria", "durple", "pinki", "mrsun")

ICON_CROPS = {
    "oren": {"slot": "01", "side": 210, "top": 8, "left_bias": 0},
    "raddy": {"slot": "02", "side": 250, "top": 20, "left_bias": 0},
    "vineria": {"slot": "05", "side": 240, "top": 8, "left_bias": -20},
    "mrsun": {"slot": "11", "side": 220, "top": 8, "left_bias": 0},
    "durple": {"slot": "12", "side": 212, "top": 77, "left_abs": 92},
    "simon": {"slot": "14", "side": 200, "top": 0, "left_abs": 35},
    "pinki": {"slot": "18", "side": 210, "top": 25, "left_bias": 0},
}

CHAR_SPRITES = {
    "oren": "Orange (Oren)",
    "raddy": "Red (Raddy)",
    "vineria": "Green (Vineria)",
    "mrsun": "Mr. Sun",
    "durple": "Purple (Durple)",
    "simon": "Yellow (Simon)",
    "pinki": "Pink (Pinki)",
}


def box_mean(x: np.ndarray, r: int = 2) -> np.ndarray:
    out = np.zeros_like(x, dtype=np.float64)
    n = (2 * r + 1) ** 2
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out += np.roll(np.roll(x, dy, axis=0), dx, axis=1)
    return out / n


def binary_dilate(mask: np.ndarray, r: int = 1) -> np.ndarray:
    m = mask.astype(bool)
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy == 0 and dx == 0:
                continue
            if dy * dy + dx * dx <= r * r + 0.01:
                out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def binary_erode(mask: np.ndarray, r: int = 1) -> np.ndarray:
    m = mask.astype(bool)
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy == 0 and dx == 0:
                continue
            if dy * dy + dx * dx <= r * r + 0.01:
                out &= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def binary_open(mask: np.ndarray, r: int = 1) -> np.ndarray:
    return binary_dilate(binary_erode(mask, r), r)


def binary_close(mask: np.ndarray, r: int = 1) -> np.ndarray:
    return binary_erode(binary_dilate(mask, r), r)


def stroke_px(h: int, w: int, mode: str) -> int:
    """Target outer stroke width in pixels for ~400px art."""
    base = max(h, w)
    if mode == "heavy_wide":
        # ~4–6px on ~400px (Polo / Oren weight)
        return int(np.clip(round(base / 80), 4, 6))
    if mode == "heavy":
        return int(np.clip(round(base / 140), 3, 4))
    return int(np.clip(round(base / 180), 2, 3))


def crush_near_black(out: np.ndarray, *, radius: int = 1, lum_hi: float = 150) -> np.ndarray:
    """Force gray/AA outline fringe next to solid black into opaque #000."""
    rgb = out[:, :, :3].astype(np.float32)
    a = out[:, :, 3]
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = np.zeros_like(lum)
    nz = mx > 1
    sat[nz] = (mx[nz] - mn[nz]) / mx[nz]
    is_black = (mx <= 2) & (a > 200)
    near_black = binary_dilate(is_black, radius) & ~is_black & (a > 40)
    aa = near_black & (lum < lum_hi) & (sat < 0.28)
    # also crush very dark near-black regardless of sat
    aa |= near_black & (lum < 55) & (mx < 80)
    out = out.copy()
    out[aa, 0] = 0
    out[aa, 1] = 0
    out[aa, 2] = 0
    out[aa, 3] = 255
    return out


def fill_ring_gaps(out: np.ndarray, *, close_r: int = 2) -> np.ndarray:
    """Morphological close on solid-black mask to fill speckles/gaps in outline rings.

    Closing radius is kept small so eye pupils / irises (large holes) are not filled.
    """
    rgb = out[:, :, :3]
    a = out[:, :, 3]
    opaque = a > 40
    is_black = (rgb.max(axis=2) <= 2) & (a > 200)
    closed = binary_close(is_black, close_r) & opaque
    fill = closed & ~is_black
    out = out.copy()
    out[fill, 0] = 0
    out[fill, 1] = 0
    out[fill, 2] = 0
    out[fill, 3] = 255
    return out


def fill_annular_speckles(out: np.ndarray) -> np.ndarray:
    """Fill light speckles trapped inside thin dark annular structures (eyes, buttons).

    A pixel is painted black if it is opaque, not already black, locally low-sat or
    mid-luma, and a strong majority of neighbors in a small ring are solid black —
    without expanding into large pupil/iris interiors (those lack a black majority).
    """
    rgb = out[:, :, :3].astype(np.float32)
    a = out[:, :, 3]
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = np.zeros_like(lum)
    nz = mx > 1
    sat[nz] = (mx[nz] - mn[nz]) / mx[nz]
    is_black = (mx <= 2) & (a > 200)
    # count black neighbors in r=2 disk
    black_f = is_black.astype(np.float32)
    neigh = box_mean(black_f, 2) * 25.0  # approx count in 5x5
    # candidates: light/gray speckles with many black neighbors
    cand = (a > 40) & ~is_black & (neigh >= 10) & (
        ((sat < 0.35) & (lum < 200)) | (lum < 90) | ((lum > 180) & (neigh >= 14) & (sat < 0.45))
    )
    # avoid painting saturated color fills (iris greens, button reds) unless nearly enclosed
    color_fill = (sat > 0.45) & (lum > 60) & (lum < 200)
    cand &= ~color_fill | (neigh >= 16)
    out = out.copy()
    out[cand, 0] = 0
    out[cand, 1] = 0
    out[cand, 2] = 0
    out[cand, 3] = 255
    return out


def strengthen_outlines(
    im: Image.Image,
    *,
    mode: str = "heavy_wide",
    heavy: bool | None = None,
) -> Image.Image:
    """Restore outer black stroke + interior line blacks on an RGBA sprite.

    mode:
      - heavy_wide (default): ~4–6px Polo-weight; gap closing; AA crush
      - heavy: medium thicken (~3–4px)
      - normal: light thicken (~2–3px)

    Legacy ``heavy=True/False`` maps to heavy / normal when mode left default
    only if explicitly passed; new callers should use mode=.
    """
    if heavy is not None and mode == "heavy_wide":
        # Explicit legacy flag overrides default only when caller still uses it.
        mode = "heavy" if heavy else "normal"

    arr = np.array(im.convert("RGBA"))
    h, w = arr.shape[:2]
    stroke = stroke_px(h, w, mode)
    wide = mode == "heavy_wide"

    # mild unsharp on RGB
    rgb0 = arr[:, :, :3].astype(np.float32)
    blur = np.stack([box_mean(rgb0[:, :, c], 1) for c in range(3)], axis=2)
    sharp = np.clip(rgb0 + 0.4 * (rgb0 - blur), 0, 255)
    a0 = arr[:, :, 3]
    arr = arr.copy()
    m = a0 > 0
    arr[m, :3] = sharp[m]

    rgb = arr[:, :, :3].astype(np.float32)
    a = arr[:, :, 3].astype(np.float32)
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = np.zeros_like(lum)
    nz = mx > 1
    sat[nz] = (mx[nz] - mn[nz]) / mx[nz]

    # kill light / colored fringe on outer edge
    near_empty = binary_dilate(a == 0, 2) & (a > 0)
    kill = ((a > 0) & (a <= 40)) | ((a > 40) & (a < 160) & near_empty & (lum > 55))
    arr[kill, 3] = 0
    a = arr[:, :, 3].astype(np.float32)
    rgb = arr[:, :, :3].astype(np.float32)
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = np.zeros_like(lum)
    nz = mx > 1
    sat[nz] = (mx[nz] - mn[nz]) / mx[nz]
    opaque = a > 40

    # outer silhouette ring (just inside opaque)
    eroded = opaque.copy()
    for _ in range(stroke):
        eroded = binary_erode(eroded, 1)
    outer_ring = opaque & ~eroded

    # interior dark lines
    local = box_mean(lum, 2)
    up = np.roll(lum, 1, 0)
    dn = np.roll(lum, -1, 0)
    lf = np.roll(lum, 1, 1)
    rt = np.roll(lum, -1, 1)
    neigh_max = np.maximum(np.maximum(up, dn), np.maximum(lf, rt))
    neigh_mean = (up + dn + lf + rt) / 4.0

    if wide:
        abs_dark = opaque & (lum < 78) & ((sat < 0.50) | (lum < 45)) & (mx < 110)
        gray_out = opaque & (lum < 95) & (sat < 0.32) & (mx < 110)
        valley = opaque & (lum < local - 10) & (lum < 130) & (neigh_max > lum + 6)
        valley &= (sat < 0.80) | (lum < 75)
    elif mode == "heavy":
        abs_dark = opaque & (lum < 70) & ((sat < 0.45) | (lum < 40)) & (mx < 100)
        gray_out = opaque & (lum < 85) & (sat < 0.28) & (mx < 100)
        valley = opaque & (lum < local - 12) & (lum < 120) & (neigh_max > lum + 8)
        valley &= (sat < 0.75) | (lum < 70)
    else:
        abs_dark = opaque & (lum < 58) & ((sat < 0.45) | (lum < 40)) & (mx < 100)
        gray_out = opaque & (lum < 85) & (sat < 0.28) & (mx < 100)
        valley = opaque & (lum < local - 20) & (lum < 95) & (neigh_max > lum + 12)
        valley &= sat < 0.40

    line_seed = abs_dark | gray_out | valley
    thin = binary_open(line_seed, 1)
    edge_like = line_seed & (neigh_max > lum + (6 if wide else 8))
    interior = thin | edge_like

    # Keep only the rim of large solid-black fills (pupils, nostrils) —
    # do NOT turn pupils/irises into solid black blobs.
    very_dark_fill = opaque & (lum < (36 if wide else 32)) & (neigh_mean < (50 if wide else 45))
    vd_erode = binary_erode(very_dark_fill, 1 if not wide else 2)
    interior = interior & (~very_dark_fill | (very_dark_fill & ~vd_erode))

    dilate_r = 2 if wide else 1
    interior_d = binary_dilate(interior, dilate_r) & opaque
    if not wide:
        if mode != "heavy":
            interior_d = interior_d & ((sat < 0.5) | (lum < 50) | interior)
        else:
            pass
    else:
        # heavy_wide: allow thickening but still prefer darker / line-adjacent pixels
        interior_d = interior_d & ((sat < 0.55) | (lum < 60) | interior | (binary_dilate(interior, 1)))

    paint = outer_ring | interior_d
    out = arr.copy()
    out[paint, 0] = 0
    out[paint, 1] = 0
    out[paint, 2] = 0
    out[paint, 3] = 255

    # final fringe pass
    a2 = out[:, :, 3]
    near_empty2 = binary_dilate(a2 == 0, 1) & (a2 > 0) & (a2 < 255)
    rgb2 = out[:, :, :3].astype(np.float32)
    lum2 = 0.2126 * rgb2[:, :, 0] + 0.7152 * rgb2[:, :, 1] + 0.0722 * rgb2[:, :, 2]
    out[near_empty2 & (lum2 > 40), 3] = 0
    dark_fr = near_empty2 & (lum2 <= 40)
    out[dark_fr, 0] = 0
    out[dark_fr, 1] = 0
    out[dark_fr, 2] = 0
    out[dark_fr, 3] = 255

    out = crush_near_black(out, radius=1 if not wide else 2, lum_hi=140 if not wide else 160)

    if wide:
        # Close thin gaps in outline rings (eye borders, Pokéball button, etc.)
        out = fill_ring_gaps(out, close_r=2)
        out = fill_annular_speckles(out)
        # second crush after fills
        out = crush_near_black(out, radius=1, lum_hi=150)
        # one more gentle close for stubborn 1px speckles
        out = fill_ring_gaps(out, close_r=1)

    return Image.fromarray(out, "RGBA")


def make_face_icons(phase1: Image.Image, char: str) -> dict[str, bytes]:
    cfg = ICON_CROPS[char]
    slot = cfg["slot"]
    w, h = phase1.size
    side = min(cfg["side"], w, h)
    top = cfg["top"]
    if "left_abs" in cfg:
        left = cfg["left_abs"]
    else:
        left = max(0, (w // 2) - side // 2 + cfg.get("left_bias", 0))
    if left + side > w:
        left = max(0, w - side)
    if top + side > h:
        top = max(0, h - side)
    face = phase1.crop((left, top, left + side, top + side))
    out: dict[str, bytes] = {}
    for name, size in ((f"{slot}-a", 68), (f"{slot}-b", 70), (f"{slot}-c", 68)):
        im = face.resize((size, size), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        out[name] = buf.getvalue()
        print(f"  icon {name} {im.size} crop=({left},{top},{side})")
    return out


def png_md5(png_bytes: bytes) -> tuple[str, str]:
    md5 = hashlib.md5(png_bytes).hexdigest()
    return md5, f"{md5}.png"


def process_art(chars: tuple[str, ...] | None = None) -> dict[str, Path]:
    """Overwrite art/<char>-phase*.png with outlined versions from _backup when present."""
    PREVIEW.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    chars = chars or TARGET_CHARS
    files: list[Path] = []
    for char in chars:
        if char in SKIP_CHARS:
            print(f"SKIP {char} (do not touch)")
            continue
        for phase in ("phase1", "phase2"):
            p = ART / f"{char}-{phase}.png"
            bak = ART / "_backup" / f"{char}-{phase}.png"
            if p.exists() or bak.exists():
                files.append(p)

    for path in files:
        char = path.name.split("-phase")[0]
        if char in SKIP_CHARS:
            continue
        bak = ART / "_backup" / path.name
        if bak.exists():
            src = Image.open(bak)
            print(f"outline {path.name} mode=heavy_wide (from backup)")
        elif path.exists():
            src = Image.open(path)
            print(f"outline {path.name} mode=heavy_wide (from current; no backup)")
        else:
            print(f"  missing {path.name}, skip")
            continue
        stroke = stroke_px(src.height, src.width, "heavy_wide")
        fixed = strengthen_outlines(src, mode="heavy_wide")
        assert fixed.size == src.size, (fixed.size, src.size)
        fixed.save(path, "PNG")
        before = src.convert("RGBA")
        after = fixed
        strip = Image.new("RGBA", (before.width * 2 + 8, before.height), (30, 30, 40, 255))
        strip.paste(before, (0, 0), before)
        strip.paste(after, (before.width + 8, 0), after)
        strip.save(PREVIEW / f"{path.stem}-compare.png")
        paths[path.name] = path
        arr = np.array(fixed)
        rgb = arr[:, :, :3]
        a = arr[:, :, 3]
        pure = ((rgb.max(axis=2) <= 2) & (a > 200)).sum()
        print(f"  -> {fixed.size} stroke~{stroke}px pure_black={int(pure)}")
    return paths


def reembed(icon_pngs: dict[str, bytes], chars: tuple[str, ...] | None = None) -> None:
    """Replace costume PNG bytes for target chars + icons; preserve centers/sizes/scripts.

    Oren (and any non-target) costumes are left pointing at their existing assets.
    """
    chars = chars or TARGET_CHARS
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    simon = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    simon_size = simon.get("size")
    simon_centers = [(c["name"], c.get("rotationCenterX"), c.get("rotationCenterY")) for c in simon["costumes"]]

    oren = next(t for t in data["targets"] if t["name"] == "Orange (Oren)")
    oren_assets = {c["name"]: (c.get("assetId"), c.get("md5ext"), c.get("rotationCenterX"), c.get("rotationCenterY")) for c in oren["costumes"]}

    art_blobs: dict[str, tuple[bytes, str, str]] = {}
    for char in chars:
        if char in SKIP_CHARS:
            continue
        for phase in ("phase1", "phase2"):
            p = ART / f"{char}-{phase}.png"
            if not p.exists():
                continue
            blob = p.read_bytes()
            md5, md5ext = png_md5(blob)
            art_blobs[p.name] = (blob, md5, md5ext)
            assets[md5ext] = blob

    bak_hashes: dict[str, str] = {}
    for p in (ART / "_backup").glob("*-phase*.png"):
        bak_hashes[hashlib.md5(p.read_bytes()).hexdigest()] = p.name
    # Also map current (pre-rewrite) hashes from sb3 won't help; classify by costume name.

    for char in chars:
        if char in SKIP_CHARS:
            continue
        sprite_name = CHAR_SPRITES[char]
        target = next(t for t in data["targets"] if t["name"] == sprite_name)
        p1_name = f"{char}-phase1.png"
        p2_name = f"{char}-phase2.png"
        if p1_name not in art_blobs and p2_name not in art_blobs:
            print(f"  no art for {char}, skip embed")
            continue
        p1 = art_blobs.get(p1_name)
        p2 = art_blobs.get(p2_name)

        for c in target["costumes"]:
            name = c["name"]
            # Mr. Sun has "idle sad" — leave alone
            if name == "idle sad":
                print(f"  {sprite_name}/{name} left untouched")
                continue
            old_md5 = c.get("assetId")
            old_art = bak_hashes.get(old_md5) if old_md5 else None
            if old_art is None:
                if name in ("idle", "idle2") or (name.startswith("anim") and "???" not in name):
                    old_art = p1_name
                elif name == "b3" or "???" in name:
                    old_art = p2_name
                else:
                    print(f"  skip unknown {sprite_name}/{name}")
                    continue

            if old_art.endswith("phase1.png"):
                if p1 is None:
                    print(f"  WARN no phase1 for {sprite_name}/{name}")
                    continue
                _, md5, ext = p1
                c["assetId"] = md5
                c["md5ext"] = ext
                c["dataFormat"] = "png"
                # Keep existing centers if already png at same size; else set from image
                im = Image.open(io.BytesIO(p1[0]))
                if c.get("bitmapResolution") != 2 or not isinstance(c.get("rotationCenterX"), (int, float)):
                    c["bitmapResolution"] = 2
                    c["rotationCenterX"] = im.size[0] / 2
                    c["rotationCenterY"] = im.size[1] / 2
                # If previous was SVG (Mr Sun horror), centers need update for new png size
                prev_ext = str(c.get("md5ext") or "")
                # already set md5ext; check size match via rotation — if centers look like SVG (~96), reset
                cx = c.get("rotationCenterX") or 0
                if cx < 120:  # likely old SVG centers
                    c["bitmapResolution"] = 2
                    c["rotationCenterX"] = im.size[0] / 2
                    c["rotationCenterY"] = im.size[1] / 2
                print(f"  {sprite_name}/{name} -> {ext} (centers {c.get('rotationCenterX')},{c.get('rotationCenterY')})")
            elif old_art.endswith("phase2.png"):
                if p2 is None:
                    print(f"  WARN no phase2 for {sprite_name}/{name}")
                    continue
                _, md5, ext = p2
                c["assetId"] = md5
                c["md5ext"] = ext
                c["dataFormat"] = "png"
                im = Image.open(io.BytesIO(p2[0]))
                cx = c.get("rotationCenterX") or 0
                # Always sync centers to new PNG dims when replacing SVG or mismatched
                if cx < 120 or abs((c.get("rotationCenterX") or 0) - im.size[0] / 2) > 2:
                    c["bitmapResolution"] = 2
                    c["rotationCenterX"] = im.size[0] / 2
                    c["rotationCenterY"] = im.size[1] / 2
                else:
                    c["bitmapResolution"] = 2
                print(f"  {sprite_name}/{name} -> {ext} (centers {c.get('rotationCenterX')},{c.get('rotationCenterY')})")

    # Icons (only slots we remade)
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
    for c in icons["costumes"]:
        if c["name"] not in icon_pngs:
            continue
        blob = icon_pngs[c["name"]]
        md5, md5ext = png_md5(blob)
        assets[md5ext] = blob
        im = Image.open(io.BytesIO(blob))
        c["assetId"] = md5
        c["md5ext"] = md5ext
        c["dataFormat"] = "png"
        c["bitmapResolution"] = 2
        c["rotationCenterX"] = im.size[0] / 2
        c["rotationCenterY"] = im.size[1] / 2
        print(f"  Icons {c['name']} -> {md5ext} {im.size}")

    # Verify Simon + Oren unchanged
    simon2 = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    assert simon2.get("size") == simon_size, (simon2.get("size"), simon_size)
    for (n, cx, cy), c in zip(simon_centers, simon2["costumes"]):
        assert c["name"] == n
        assert c.get("rotationCenterX") == cx and c.get("rotationCenterY") == cy, (
            n,
            cx,
            cy,
            c.get("rotationCenterX"),
            c.get("rotationCenterY"),
        )
    print(f"  Simon size={simon_size} centers preserved OK")

    oren2 = next(t for t in data["targets"] if t["name"] == "Orange (Oren)")
    for c in oren2["costumes"]:
        prev = oren_assets[c["name"]]
        assert c.get("assetId") == prev[0] and c.get("md5ext") == prev[1], (c["name"], c.get("md5ext"), prev[1])
        assert c.get("rotationCenterX") == prev[2] and c.get("rotationCenterY") == prev[3]
    print("  Oren costumes untouched OK")

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
    SB3.write_bytes(buf.getvalue())
    print(f"wrote {SB3} ({SB3.stat().st_size} bytes)")


def main() -> None:
    print("=== 1) Strengthen outlines (heavy_wide) on target art — skip Oren ===")
    process_art(TARGET_CHARS)

    print("=== 2) Remake face-zoom icons from repaired phase1 ===")
    icon_pngs: dict[str, bytes] = {}
    for char in TARGET_CHARS:
        if char in SKIP_CHARS:
            continue
        p1_path = ART / f"{char}-phase1.png"
        if not p1_path.exists():
            print(f"  skip icons {char}: no phase1")
            continue
        p1 = Image.open(p1_path)
        icon_pngs.update(make_face_icons(p1, char))

    print("=== 3) Re-embed into sprunki-base.sb3 ===")
    reembed(icon_pngs, TARGET_CHARS)
    print("DONE")


if __name__ == "__main__":
    main()

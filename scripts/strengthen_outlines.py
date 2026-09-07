#!/usr/bin/env python3
"""Strengthen black outlines on custom Sprunki art; remake face icons; re-embed sb3."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "art"
SB3 = ROOT / "sprunki-base.sb3"
PREVIEW = ART / "_preview"

# Icon face crops: (side, top, left_offset_from_center) — left_offset 0 = centered
# left may also be absolute via left_abs
ICON_CROPS = {
    "oren": {"slot": "01", "side": 210, "top": 8, "left_bias": 0},  # left=82 on 374w => bias ~0? (374-210)//2=82
    "raddy": {"slot": "02", "side": 250, "top": 20, "left_bias": 0},
    "vineria": {"slot": "05", "side": 240, "top": 8, "left_bias": -20},
    "durple": {"slot": "12", "side": 212, "top": 77, "left_abs": 92},
    "simon": {"slot": "14", "side": 200, "top": 0, "left_abs": 35},
    "pinki": {"slot": "18", "side": 210, "top": 25, "left_bias": 0},
}

CHAR_SPRITES = {
    "oren": "Orange (Oren)",
    "raddy": "Red (Raddy)",
    "vineria": "Green (Vineria)",
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


def unsharp_rgb(arr: np.ndarray, amount: float = 0.45) -> np.ndarray:
    """Slight unsharp on RGB where alpha > 0; keep alpha."""
    rgb = arr[:, :, :3].astype(np.float32)
    a = arr[:, :, 3]
    blur = np.zeros_like(rgb)
    for c in range(3):
        blur[:, :, c] = box_mean(rgb[:, :, c], 1)
    sharp = rgb + amount * (rgb - blur)
    sharp = np.clip(sharp, 0, 255)
    out = arr.copy()
    m = a > 0
    out[m, :3] = sharp[m]
    return out


def strengthen_outlines(im: Image.Image, *, heavy: bool = False) -> Image.Image:
    """Restore outer black stroke + thin interior line blacks on an RGBA sprite."""
    arr = np.array(im.convert("RGBA"))
    h, w = arr.shape[:2]
    stroke = max(2, min(3, round(max(h, w) / 180)))
    if heavy:
        stroke = max(stroke, 3)

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

    abs_dark = opaque & (lum < (70 if heavy else 58)) & ((sat < 0.45) | (lum < 40)) & (mx < 100)
    gray_out = opaque & (lum < 85) & (sat < 0.28) & (mx < 100)
    if heavy:
        valley = opaque & (lum < local - 12) & (lum < 120) & (neigh_max > lum + 8)
        valley &= (sat < 0.75) | (lum < 70)
    else:
        valley = opaque & (lum < local - 20) & (lum < 95) & (neigh_max > lum + 12)
        valley &= sat < 0.40

    line_seed = abs_dark | gray_out | valley
    thin = binary_open(line_seed, 1)
    edge_like = line_seed & (neigh_max > lum + 8)
    interior = thin | edge_like

    very_dark_fill = opaque & (lum < 32) & (neigh_mean < 45)
    vd_erode = binary_erode(very_dark_fill, 1)
    interior = interior & (~very_dark_fill | (very_dark_fill & ~vd_erode))

    interior_d = binary_dilate(interior, 1) & opaque
    if not heavy:
        interior_d = interior_d & ((sat < 0.5) | (lum < 50) | interior)

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

    # crush gray AA sitting against black outline
    is_black = (out[:, :, 0] <= 2) & (out[:, :, 1] <= 2) & (out[:, :, 2] <= 2) & (out[:, :, 3] > 200)
    near_black = binary_dilate(is_black, 1) & ~is_black & (out[:, :, 3] > 40)
    sat2 = np.zeros_like(lum2)
    mx2 = rgb2.max(axis=2)
    mn2 = rgb2.min(axis=2)
    nz2 = mx2 > 1
    sat2[nz2] = (mx2[nz2] - mn2[nz2]) / mx2[nz2]
    aa = near_black & (lum2 > 40) & (lum2 < 140) & (sat2 < 0.25)
    out[aa, 0] = 0
    out[aa, 1] = 0
    out[aa, 2] = 0
    out[aa, 3] = 255

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


def process_art() -> dict[str, Path]:
    """Overwrite all art/*-phase*.png with outlined versions. Returns map name->path."""
    PREVIEW.mkdir(parents=True, exist_ok=True)
    paths = {}
    files = sorted(ART.glob("*-phase1.png")) + sorted(ART.glob("*-phase2.png"))
    for path in files:
        char = path.name.split("-phase")[0]
        heavy = char == "vineria"
        print(f"outline {path.name} heavy={heavy}")
        src = Image.open(path)
        # use backup if present so re-runs are idempotent-ish from original
        bak = ART / "_backup" / path.name
        if bak.exists():
            src = Image.open(bak)
        fixed = strengthen_outlines(src, heavy=heavy)
        assert fixed.size == src.size, (fixed.size, src.size)
        fixed.save(path, "PNG")
        # preview strip: before | after
        before = src.convert("RGBA")
        after = fixed
        strip = Image.new("RGBA", (before.width * 2 + 8, before.height), (30, 30, 40, 255))
        strip.paste(before, (0, 0), before)
        strip.paste(after, (before.width + 8, 0), after)
        strip.save(PREVIEW / f"{path.stem}-compare.png")
        paths[path.name] = path
        # stats
        arr = np.array(fixed)
        rgb = arr[:, :, :3]
        a = arr[:, :, 3]
        pure = ((rgb.max(axis=2) <= 2) & (a > 200)).sum()
        print(f"  -> {fixed.size} pure_black={int(pure)}")
    return paths


def reembed(icon_pngs: dict[str, bytes]) -> None:
    """Replace costume PNG bytes for custom chars + icons; preserve centers/sizes/scripts."""
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    # snapshot Simon size + centers
    simon = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    simon_size = simon.get("size")
    simon_centers = [(c["name"], c.get("rotationCenterX"), c.get("rotationCenterY")) for c in simon["costumes"]]

    # map art file -> bytes + md5
    art_blobs: dict[str, tuple[bytes, str, str]] = {}
    for p in ART.glob("*-phase*.png"):
        blob = p.read_bytes()
        md5, md5ext = png_md5(blob)
        art_blobs[p.name] = (blob, md5, md5ext)
        assets[md5ext] = blob

    # For each character, find which costumes currently point at phase1 vs phase2 art
    # by matching old hashes from backup
    bak_hashes: dict[str, str] = {}  # md5 -> art name
    for p in (ART / "_backup").glob("*-phase*.png"):
        bak_hashes[hashlib.md5(p.read_bytes()).hexdigest()] = p.name
    # also current pre-update was backup; costumes still have old md5s = backup hashes
    # After first run costumes may already point to new — also index current art names by
    # matching costume md5 to either backup or current art stem via sprite mapping.

    for char, sprite_name in CHAR_SPRITES.items():
        target = next(t for t in data["targets"] if t["name"] == sprite_name)
        p1_name = f"{char}-phase1.png"
        p2_name = f"{char}-phase2.png"
        p1_blob, p1_md5, p1_ext = art_blobs[p1_name]
        p2_blob, p2_md5, p2_ext = art_blobs[p2_name]

        for c in target["costumes"]:
            name = c["name"]
            old_md5 = c.get("assetId")
            old_art = bak_hashes.get(old_md5)
            # Fallback: classify by costume name convention
            if old_art is None:
                if name in ("idle", "idle2") or (name.startswith("anim") and "???" not in name):
                    old_art = p1_name
                elif name == "b3" or "???" in name:
                    old_art = p2_name
                else:
                    print(f"  skip unknown {sprite_name}/{name}")
                    continue

            if old_art.endswith("phase1.png"):
                c["assetId"] = p1_md5
                c["md5ext"] = p1_ext
                c["dataFormat"] = "png"
                # preserve rotation centers & bitmapResolution
                print(f"  {sprite_name}/{name} -> {p1_ext} (centers kept {c.get('rotationCenterX')},{c.get('rotationCenterY')})")
            elif old_art.endswith("phase2.png"):
                c["assetId"] = p2_md5
                c["md5ext"] = p2_ext
                c["dataFormat"] = "png"
                print(f"  {sprite_name}/{name} -> {p2_ext} (centers kept {c.get('rotationCenterX')},{c.get('rotationCenterY')})")

    # Icons
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

    # Verify Simon size + centers unchanged
    simon2 = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    assert simon2.get("size") == simon_size, (simon2.get("size"), simon_size)
    for (n, cx, cy), c in zip(simon_centers, simon2["costumes"]):
        assert c["name"] == n
        assert c.get("rotationCenterX") == cx and c.get("rotationCenterY") == cy, (n, cx, cy, c.get("rotationCenterX"), c.get("rotationCenterY"))
    print(f"  Simon size={simon_size} centers preserved OK")

    # Write sb3 with only referenced assets
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
    print("=== 1) Strengthen outlines on all phase art ===")
    process_art()

    print("=== 2) Remake face-zoom icons from repaired phase1 ===")
    icon_pngs: dict[str, bytes] = {}
    for char in ICON_CROPS:
        p1 = Image.open(ART / f"{char}-phase1.png")
        icon_pngs.update(make_face_icons(p1, char))

    print("=== 3) Re-embed into sprunki-base.sb3 ===")
    reembed(icon_pngs)
    print("DONE")


if __name__ == "__main__":
    main()

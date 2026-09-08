#!/usr/bin/env python3
"""Add Black? (Mr. Black) Phase 1 + Phase 2 art, Icons 20-*, sticky Phase 2."""
from __future__ import annotations

import io
import json
import sys
import zipfile
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_phase2_sticky import (  # noqa: E402
    BROADCAST_PHASE2,
    TARGET_H,
    append_sticky_forever,
    ensure_phase2_prefix,
    new_id,
    png_asset,
    rebuild_switch_costume,
    set_costume_png,
)
from strengthen_outlines import strengthen_outlines  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
ART_P1 = ROOT / "art" / "mrblack-phase1.png"
ART_P2 = ROOT / "art" / "mrblack-phase2.png"
SRC_P1 = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments/"
    "bebb8a9639f3396c7b81aa070f966baec8b27c2394cbbbda2a64daa478b8ce1e.png"
)
SRC_P2 = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments/"
    "76a49943fbe837b3e2ae9f03b1c6fa80a9cd09ea6dbab6474d20f467ccae39e7.png"
)

SPRITE = "Black?"
POLO_ID = "iY@x:9-akvVBr3xjgzNR"  # Polo Im On RN on Black?

PHASE1_NAMES = ("idle", "idle2", "anim", "anim2", "anim3", "anim4")
PHASE2_NAMES = ("b3", "anim???", "anim???2", "anim???3", "anim???4")


def binary_dilate(mask: np.ndarray, r: int = 1) -> np.ndarray:
    m = mask.astype(bool)
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy * dy + dx * dx <= r * r + 0.01:
                out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def prep_mrblack(im: Image.Image) -> Image.Image:
    """
    Prep Mr. Black WITHOUT flood-filling all black.
    Keep character black body by growing from red/white/chromatic accents
    through connected opaque pixels; only knock unreached near-black leftover bg.
    """
    arr = np.array(im.convert("RGBA"))
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3].astype(np.int16)
    a = arr[:, :, 3]

    # Accent seeds: red, white, any chromatic non-black
    red = (rgb[:, :, 0] > 100) & (rgb[:, :, 1] < 100) & (rgb[:, :, 2] < 100) & (a > 30)
    white = (rgb.min(axis=2) > 180) & (a > 30)
    chromatic = (rgb.max(axis=2) - rgb.min(axis=2) > 35) & (rgb.max(axis=2) > 45) & (a > 30)
    seeds = red | white | chromatic

    # Flood through opaque/near-opaque from accents → full character including black body
    body = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    ys, xs = np.where(seeds)
    for y, x in zip(ys.tolist(), xs.tolist()):
        body[y, x] = True
        q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not body[ny, nx]:
                if a[ny, nx] > 20:
                    body[ny, nx] = True
                    q.append((ny, nx))

    # Keep semi-transparent wisps near body (flame AA)
    keep = body | (binary_dilate(body, 3) & (a > 0))

    # Corner-connected leftover near-black NOT in keep → transparent
    near_black = (rgb.max(axis=2) <= 28) & (a > 0) & ~keep
    knock = np.zeros((h, w), dtype=bool)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if (a[y, x] == 0 or near_black[y, x]) and not knock[y, x]:
                knock[y, x] = True
                q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if (a[y, x] == 0 or near_black[y, x]) and not knock[y, x]:
                knock[y, x] = True
                q.append((y, x))
    # also start from existing transparent
    ys, xs = np.where(a == 0)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if not knock[y, x]:
            knock[y, x] = True
            q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not knock[ny, nx]:
                if near_black[ny, nx] or a[ny, nx] == 0:
                    knock[ny, nx] = True
                    q.append((ny, nx))

    out = arr.copy()
    out[knock & ~keep, 3] = 0
    out[~keep, 3] = 0

    # Kill light fringe on outer edge only (not body black)
    a2 = out[:, :, 3]
    rgb2 = out[:, :, :3].astype(np.float32)
    lum = 0.2126 * rgb2[:, :, 0] + 0.7152 * rgb2[:, :, 1] + 0.0722 * rgb2[:, :, 2]
    near_empty = binary_dilate(a2 == 0, 2) & (a2 > 0)
    light_fringe = near_empty & (lum > 60) & (a2 < 220)
    out[light_fringe, 3] = 0

    img = Image.fromarray(out, "RGBA")
    bbox = img.split()[-1].getbbox()
    if bbox:
        l, t, r, btm = bbox
        pad = 2
        l = max(0, l - pad)
        t = max(0, t - pad)
        r = min(img.width, r + pad)
        btm = min(img.height, btm + pad)
        img = img.crop((l, t, r, btm))
    if img.height != TARGET_H:
        nw = max(1, round(img.width * TARGET_H / img.height))
        img = img.resize((nw, TARGET_H), Image.Resampling.LANCZOS)
    return img


def make_face_icons(phase1: Image.Image) -> dict[str, bytes]:
    """Face-zoom: hat band + eyes + cravat for Icons 20-a/b/c."""
    w, h = phase1.size
    # Tighter face zoom (Phase 1 face clearly visible)
    side = min(200, w, h)
    top = 28
    left = max(0, (w - side) // 2)
    if left + side > w:
        left = max(0, w - side)
    face = phase1.crop((left, top, left + side, top + side))
    out: dict[str, bytes] = {}
    for name, size in (("20-a", 68), ("20-b", 70), ("20-c", 68)):
        im = face.resize((size, size), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        out[name] = buf.getvalue()
        print(f"  icon {name} {im.size} crop=({left},{top},{side})")
    return out


def ensure_phase2_hat(target: dict) -> str:
    """Create Phase 2 broadcast hat if missing; return hat id."""
    blocks = target["blocks"]
    for bid, b in blocks.items():
        if not isinstance(b, dict):
            continue
        if b.get("opcode") != "event_whenbroadcastreceived":
            continue
        opt = (b.get("fields") or {}).get("BROADCAST_OPTION")
        if opt and opt[0] == "Phase 2":
            print("  Phase 2 hat already present")
            return bid
    hat = new_id(blocks)
    blocks[hat] = {
        "opcode": "event_whenbroadcastreceived",
        "next": None,
        "parent": None,
        "inputs": {},
        "fields": {"BROADCAST_OPTION": [BROADCAST_PHASE2[0], BROADCAST_PHASE2[1]]},
        "shadow": False,
        "topLevel": True,
        "x": 100,
        "y": 100,
    }
    print(f"  created Phase 2 hat {hat}")
    return hat


def ensure_costumes(target: dict) -> None:
    """Ensure idle/idle2/anim* + b3/anim???* costume slots exist."""
    by_name = {c["name"]: c for c in target["costumes"]}
    # Use idle as template for metadata fields we copy
    idle = by_name.get("idle") or target["costumes"][0]
    template = {k: idle[k] for k in idle}

    def add(name: str) -> None:
        if name in by_name:
            return
        c = {k: template[k] for k in template}
        c["name"] = name
        target["costumes"].append(c)
        by_name[name] = c
        print(f"  inserted costume slot {name}")

    # Desired order-ish: idle, idle2, b3, anim..., anim???...
    for n in PHASE1_NAMES:
        add(n)
    for n in PHASE2_NAMES:
        add(n)

    # Reorder: idle, idle2, b3, anim*, anim???*
    order = list(PHASE1_NAMES[:2]) + ["b3"] + list(PHASE1_NAMES[2:]) + list(PHASE2_NAMES[1:])
    remaining = [c for c in target["costumes"] if c["name"] not in order]
    ordered = []
    by_name = {c["name"]: c for c in target["costumes"]}
    for n in order:
        if n in by_name:
            ordered.append(by_name[n])
    ordered.extend(remaining)
    # dedupe by name preserving first
    seen = set()
    final = []
    for c in ordered:
        if c["name"] in seen:
            continue
        seen.add(c["name"])
        final.append(c)
    target["costumes"] = final


def assign_art(target: dict, p1_bytes: bytes, p2_bytes: bytes, assets: dict) -> None:
    md1, ext1, cx1, cy1 = png_asset(p1_bytes)
    md2, ext2, cx2, cy2 = png_asset(p2_bytes)
    assets[ext1] = p1_bytes
    assets[ext2] = p2_bytes
    for c in target["costumes"]:
        name = c["name"]
        if name == "b3" or "???" in name:
            set_costume_png(c, md2, ext2, cx2, cy2)
            print(f"  {name} -> phase2 {ext2}")
        elif name in PHASE1_NAMES or (
            name.startswith("anim") and "???" not in name
        ) or name in ("idle", "idle2"):
            set_costume_png(c, md1, ext1, cx1, cy1)
            print(f"  {name} -> phase1 {ext1}")
        else:
            print(f"  {name} left ({c.get('md5ext')})")


def assign_icons(data: dict, icon_pngs: dict[str, bytes], assets: dict) -> None:
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
    for c in icons["costumes"]:
        if c["name"] not in icon_pngs:
            continue
        blob = icon_pngs[c["name"]]
        md5, md5ext, cx, cy = png_asset(blob)
        assets[md5ext] = blob
        set_costume_png(c, md5, md5ext, cx, cy)
        print(f"  Icons {c['name']} -> {md5ext} {Image.open(io.BytesIO(blob)).size}")


def main() -> None:
    print("1) Prep Mr. Black Phase 1 (accent-seeded key, no black flood)")
    p1 = prep_mrblack(Image.open(SRC_P1))
    print(f"  keyed {p1.size}")
    p1 = strengthen_outlines(p1, heavy=False)
    ART_P1.parent.mkdir(parents=True, exist_ok=True)
    p1.save(ART_P1, "PNG")
    p1_bytes = ART_P1.read_bytes()
    print(f"  saved {ART_P1.name} {p1.size} ({len(p1_bytes)} bytes)")

    print("2) Prep Mr. Black Phase 2")
    p2 = prep_mrblack(Image.open(SRC_P2))
    print(f"  keyed {p2.size}")
    p2 = strengthen_outlines(p2, heavy=False)
    p2.save(ART_P2, "PNG")
    p2_bytes = ART_P2.read_bytes()
    print(f"  saved {ART_P2.name} {p2.size} ({len(p2_bytes)} bytes)")

    # previews
    prev = ROOT / "art" / "_preview"
    prev.mkdir(exist_ok=True)
    for label, im in (("p1", p1), ("p2", p2)):
        bg = Image.new("RGBA", (im.width + 20, im.height + 20), (40, 120, 180, 255))
        bg.paste(im, (10, 10), im)
        bg.save(prev / f"mrblack-{label}-final-on-sky.png")

    print("3) Face icons 20-*")
    icon_pngs = make_face_icons(p1)

    print("4) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    simon = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    simon_size = simon.get("size")
    simon_cx = simon["costumes"][0].get("rotationCenterX")

    black = next(t for t in data["targets"] if t["name"] == SPRITE)
    print("5) Ensure costume slots")
    ensure_costumes(black)

    print("6) Assign phase art")
    assign_art(black, p1_bytes, p2_bytes, assets)

    print("7) Icons 20-a/b/c")
    assign_icons(data, icon_pngs, assets)

    print("8) Sticky Phase 2 scripts")
    ensure_phase2_hat(black)
    hat = ensure_phase2_prefix(black)
    append_sticky_forever(black, hat)
    rebuild_switch_costume(black, POLO_ID)

    simon2 = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    assert simon2.get("size") == simon_size
    assert simon2["costumes"][0].get("rotationCenterX") == simon_cx
    print(f"  Simon still size={simon_size} cx={simon_cx} OK")

    print("9) Write sb3")
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
    print(f"  wrote {SB3} ({SB3.stat().st_size} bytes)")
    print("DONE")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Add Brown (brud) Phase 1 art + Icons 07 face zooms (Slowpoke face only). Phase 2 not yet."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
ART_P1 = ROOT / "art" / "brud-phase1.png"
PREV = ROOT / "art" / "_preview"
OUT_CHECK = Path("/workspace/brud-p1-check.png")

SPRITE = "Brown (brud)"
ICON_SLOT = "07"
# Face crop on phase1 (250x400): eyes+snout+mouth below bucket (not full body/bucket)
ICON_LEFT, ICON_TOP, ICON_SIDE = 15, 50, 160


def png_asset(png_bytes: bytes) -> tuple[str, str, float, float]:
    md5 = hashlib.md5(png_bytes).hexdigest()
    md5ext = f"{md5}.png"
    im = Image.open(io.BytesIO(png_bytes))
    w, h = im.size
    return md5, md5ext, w / 2, h / 2


def set_costume_png(c: dict, md5: str, md5ext: str, cx: float, cy: float) -> None:
    c["assetId"] = md5
    c["md5ext"] = md5ext
    c["dataFormat"] = "png"
    c["bitmapResolution"] = 2
    c["rotationCenterX"] = cx
    c["rotationCenterY"] = cy


def make_face_icons(phase1: Image.Image) -> dict[str, bytes]:
    face = phase1.crop(
        (ICON_LEFT, ICON_TOP, ICON_LEFT + ICON_SIDE, ICON_TOP + ICON_SIDE)
    )
    out: dict[str, bytes] = {}
    for name, size in (
        (f"{ICON_SLOT}-a", 68),
        (f"{ICON_SLOT}-b", 70),
        (f"{ICON_SLOT}-c", 68),
    ):
        im = face.resize((size, size), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        out[name] = buf.getvalue()
        print(f"  icon {name} {im.size} crop=({ICON_LEFT},{ICON_TOP},{ICON_SIDE})")
    return out


def assign_phase1_body(target: dict, p1_bytes: bytes, assets: dict) -> None:
    md5, md5ext, cx, cy = png_asset(p1_bytes)
    assets[md5ext] = p1_bytes
    for c in target["costumes"]:
        name = c["name"]
        if name in ("idle", "idle2") or (
            name.startswith("anim") and "???" not in name
        ):
            set_costume_png(c, md5, md5ext, cx, cy)
            print(f"  costume {name} → phase1 {md5ext}")
        else:
            print(f"  costume {name} left ({c.get('md5ext')})")


def checker(img: Image.Image, cell: int = 16) -> Image.Image:
    ww, hh = img.size
    bg = Image.new("RGBA", (ww, hh))
    px = bg.load()
    for y in range(hh):
        for x in range(ww):
            c = 180 if (x // cell + y // cell) % 2 == 0 else 220
            px[x, y] = (c, c, c, 255)
    bg.alpha_composite(img)
    return bg


def main() -> None:
    PREV.mkdir(parents=True, exist_ok=True)
    assert ART_P1.exists(), ART_P1

    print("1) Face icons from Phase 1 (face only)")
    p1_im = Image.open(ART_P1).convert("RGBA")
    print(f"  source {ART_P1.name} {p1_im.size}")
    icon_pngs = make_face_icons(p1_im)
    Image.open(io.BytesIO(icon_pngs[f"{ICON_SLOT}-a"])).save(
        PREV / f"icon-new-{ICON_SLOT}a.png"
    )
    checker(p1_im).save(OUT_CHECK)
    print(f"  wrote {OUT_CHECK}")

    print("2) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    target = next(t for t in data["targets"] if t["name"] == SPRITE)
    print(f"3) Brud size={target.get('size')} → 55 (keep; Fun Bot shrink untouched)")
    target["size"] = 55.0

    # Do not touch Fun Bot
    fb = next(t for t in data["targets"] if t["name"] == "Fun Bot")
    print(f"   Fun Bot size left at {fb.get('size')}")

    print("4) Assign Phase 1 costumes (idle/idle2/non-??? anim*)")
    assign_phase1_body(target, ART_P1.read_bytes(), assets)

    print("5) Icons 07-* (no fake* hard-switches)")
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
    for c in icons["costumes"]:
        if c["name"] not in icon_pngs:
            continue
        blob = icon_pngs[c["name"]]
        md5, md5ext, cx, cy = png_asset(blob)
        assets[md5ext] = blob
        set_costume_png(c, md5, md5ext, cx, cy)
        print(f"  Icons {c['name']} → {md5ext} {Image.open(io.BytesIO(blob)).size} br=2")

    print("6) Write sb3")
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

    with zipfile.ZipFile(SB3, "r") as z:
        data2 = json.loads(z.read("project.json"))
    brud = next(t for t in data2["targets"] if t["name"] == SPRITE)
    print("VERIFY Brud size", brud.get("size"))
    print("VERIFY costumes:")
    for c in brud["costumes"]:
        print(f"  {c['name']}: {c.get('md5ext')} br={c.get('bitmapResolution')} fmt={c.get('dataFormat')}")
    fb2 = next(t for t in data2["targets"] if t["name"] == "Fun Bot")
    print("VERIFY Fun Bot size unchanged", fb2.get("size"))
    ic = next(t for t in data2["targets"] if t["name"] == "Icons")
    for c in ic["costumes"]:
        if c["name"].startswith("07"):
            print(
                f"  Icons {c['name']}: {c.get('md5ext')} {c.get('dataFormat')} br={c.get('bitmapResolution')}"
            )


if __name__ == "__main__":
    main()

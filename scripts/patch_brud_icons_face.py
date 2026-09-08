#!/usr/bin/env python3
"""Zoom Brown (brud) shelf Icons 07-* to Slowpoke face + visible bucket.

Does not touch Tunner (Icons 15) or any other slots.
Crop from art/brud-phase1.png — bucket + face (face sits lower in the icon).
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
ART_P1 = ROOT / "art" / "brud-phase1.png"
PREV = ROOT / "art" / "_preview"
OUT_CHECK = Path("/workspace/icon-check-brud.png")

ICON_SLOT = "07"
# Face lower in frame so bucket is visible (was 15,105,150 face-only)
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


def main() -> None:
    PREV.mkdir(parents=True, exist_ok=True)
    assert ART_P1.exists(), ART_P1

    print("1) Face+bucket icons from Phase 1 (face lower in frame)")
    p1_im = Image.open(ART_P1).convert("RGBA")
    print(f"  source {ART_P1.name} {p1_im.size}")
    print(
        f"  crop box=({ICON_LEFT},{ICON_TOP},"
        f"{ICON_LEFT + ICON_SIDE},{ICON_TOP + ICON_SIDE})"
    )
    icon_pngs = make_face_icons(p1_im)
    Image.open(io.BytesIO(icon_pngs[f"{ICON_SLOT}-a"])).save(
        PREV / f"icon-new-{ICON_SLOT}a-face.png"
    )

    # QA: 4x nearest + crosshair on checker-ish dark bg
    blob_a = icon_pngs[f"{ICON_SLOT}-a"]
    im = Image.open(io.BytesIO(blob_a)).convert("RGBA")
    scale = 4
    big = im.resize((im.width * scale, im.height * scale), Image.Resampling.NEAREST)
    canvas = Image.new("RGBA", (big.width + 40, big.height + 80), (32, 32, 40, 255))
    canvas.paste(big, (20, 40), big)
    d = ImageDraw.Draw(canvas)
    cx, cy = 20 + big.width // 2, 40 + big.height // 2
    d.line([(cx, 40), (cx, 40 + big.height)], fill=(0, 255, 0, 160), width=1)
    d.line([(20, cy), (20 + big.width, cy)], fill=(0, 255, 0, 160), width=1)
    d.text(
        (8, 8),
        f"brud icon QA face-only ({ICON_LEFT},{ICON_TOP},{ICON_SIDE}) 68px@4x",
        fill=(220, 220, 220, 255),
    )
    canvas.save(OUT_CHECK)
    print(f"  wrote {OUT_CHECK}")

    print("2) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    # Snapshot Tunner 15-* md5s before write
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
    tunner_before = {
        c["name"]: c.get("md5ext")
        for c in icons["costumes"]
        if c["name"].startswith("15")
    }
    other_before = {
        c["name"]: (c.get("md5ext"), c.get("bitmapResolution"))
        for c in icons["costumes"]
        if not c["name"].startswith("07")
    }

    print("3) Assign Icons 07-a/b/c only")
    for c in icons["costumes"]:
        if c["name"] not in icon_pngs:
            continue
        blob = icon_pngs[c["name"]]
        md5, md5ext, cx, cy = png_asset(blob)
        assets[md5ext] = blob
        set_costume_png(c, md5, md5ext, cx, cy)
        print(
            f"  Icons {c['name']} → {md5ext} "
            f"{Image.open(io.BytesIO(blob)).size} br=2 cx={cx} cy={cy}"
        )

    print("4) Write sb3")
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

    print("5) Verify")
    with zipfile.ZipFile(SB3, "r") as z:
        data2 = json.loads(z.read("project.json"))
        icons2 = next(t for t in data2["targets"] if t["name"] == "Icons")
        for c in icons2["costumes"]:
            if c["name"].startswith("07"):
                blob = z.read(c["md5ext"])
                im2 = Image.open(io.BytesIO(blob))
                print(
                    f"  Icons {c['name']}: {c['md5ext'][:12]}… {im2.size} "
                    f"br={c.get('bitmapResolution')} fmt={c.get('dataFormat')}"
                )
                assert c.get("bitmapResolution") == 2
                assert c.get("dataFormat") == "png"
                assert im2.size[0] in (68, 70)
            if c["name"].startswith("15"):
                assert c.get("md5ext") == tunner_before[c["name"]], (
                    c["name"],
                    c.get("md5ext"),
                    tunner_before[c["name"]],
                )
                print(f"  Tunner Icons {c['name']} unchanged {c.get('md5ext')[:12]}…")
        # other slots unchanged
        for c in icons2["costumes"]:
            if c["name"].startswith("07"):
                continue
            prev = other_before.get(c["name"])
            if prev:
                assert (c.get("md5ext"), c.get("bitmapResolution")) == prev, c["name"]
        print("  other icon slots unchanged OK")
    print("DONE")


if __name__ == "__main__":
    main()

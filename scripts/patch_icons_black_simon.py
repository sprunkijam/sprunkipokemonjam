#!/usr/bin/env python3
"""Fix Mr. Black shelf icon (fake20) + center Simon Icons 14-* face crop."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
ART_BLACK = ROOT / "art" / "mrblack-phase1.png"
ART_SIMON = ROOT / "art" / "simon-phase1.png"
PREV = ROOT / "art" / "_preview"
OUT_BLACK = Path("/workspace/icon-check-black.png")
OUT_SIMON = Path("/workspace/icon-check-simon.png")

# Black Phase 1 face/hat crop (source coords on mrblack-phase1.png)
BLACK_LEFT, BLACK_TOP, BLACK_SIDE = 31, 10, 200

# Simon face crop centered on eyes/cheeks (not full-sprite bbox / tail)
# eye_mid≈90.5, cheek_mid≈97.2 → use avg≈93.8; side 168; slight up for forehead
SIMON_LEFT, SIMON_TOP, SIMON_SIDE = 9, 99, 168


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


def make_icons(src: Image.Image, left: int, top: int, side: int) -> dict[str, bytes]:
    crop = src.crop((left, top, left + side, top + side))
    out: dict[str, bytes] = {}
    for name, size in (("a", 68), ("b", 70), ("c", 68)):
        im = crop.resize((size, size), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        out[name] = buf.getvalue()
    return out


def assign_triplet(icons: dict, prefix: str, pngs: dict[str, bytes], assets: dict) -> None:
    for suffix in ("a", "b", "c"):
        name = f"{prefix}-{suffix}"
        blob = pngs[suffix]
        md5, md5ext, cx, cy = png_asset(blob)
        assets[md5ext] = blob
        for c in icons["costumes"]:
            if c["name"] == name:
                set_costume_png(c, md5, md5ext, cx, cy)
                print(f"  Icons {name} -> {md5ext} {Image.open(io.BytesIO(blob)).size} cx={cx} cy={cy}")


def fix_create_icons_fake20(icons: dict) -> None:
    """Create icons hardcoded 20-a-fake20 for Black shelf clone — retarget to 20-a."""
    blocks = icons["blocks"]
    fixed = 0
    for bid, b in blocks.items():
        if not isinstance(b, dict):
            continue
        if b.get("opcode") != "looks_costume":
            continue
        fields = b.get("fields") or {}
        costume = fields.get("COSTUME")
        if not costume:
            continue
        if costume[0] == "20-a-fake20":
            print(f"  retarget looks_costume {bid}: 20-a-fake20 -> 20-a")
            fields["COSTUME"] = ["20-a", None]
            fixed += 1
    if fixed != 1:
        raise RuntimeError(f"expected exactly 1 fake20 costume switch, found {fixed}")


def also_replace_fake20_assets(icons: dict, pngs: dict[str, bytes], assets: dict) -> None:
    """Belt-and-suspenders: if anything still shows fake20, serve Phase 1 PNG."""
    mapping = {"20-a-fake20": "a", "20-b-fake20": "b"}
    for c in icons["costumes"]:
        if c["name"] not in mapping:
            continue
        blob = pngs[mapping[c["name"]]]
        md5, md5ext, cx, cy = png_asset(blob)
        assets[md5ext] = blob
        set_costume_png(c, md5, md5ext, cx, cy)
        # keep costume *name* so contains-fake20 logic still works if used
        print(f"  Icons {c['name']} asset -> {md5ext} (png, name unchanged)")


def main() -> None:
    PREV.mkdir(parents=True, exist_ok=True)

    print("1) Build Black Icons 20-* from Phase 1 face/hat crop")
    black = Image.open(ART_BLACK).convert("RGBA")
    print(f"  source {ART_BLACK.name} {black.size}")
    print(f"  crop box=({BLACK_LEFT},{BLACK_TOP},{BLACK_LEFT+BLACK_SIDE},{BLACK_TOP+BLACK_SIDE})")
    black_pngs = make_icons(black, BLACK_LEFT, BLACK_TOP, BLACK_SIDE)

    print("2) Build Simon Icons 14-* centered on eyes/cheeks")
    simon = Image.open(ART_SIMON).convert("RGBA")
    print(f"  source {ART_SIMON.name} {simon.size}")
    print(f"  crop box=({SIMON_LEFT},{SIMON_TOP},{SIMON_LEFT+SIMON_SIDE},{SIMON_TOP+SIMON_SIDE})")
    simon_pngs = make_icons(simon, SIMON_LEFT, SIMON_TOP, SIMON_SIDE)

    # QA previews
    Image.open(io.BytesIO(black_pngs["a"])).save(PREV / "icon-new-20a.png")
    Image.open(io.BytesIO(simon_pngs["a"])).save(PREV / "icon-new-14a.png")
    # checker composites
    for label, blob, outp in (
        ("black", black_pngs["a"], OUT_BLACK),
        ("simon", simon_pngs["a"], OUT_SIMON),
    ):
        im = Image.open(io.BytesIO(blob)).convert("RGBA")
        scale = 4
        big = im.resize((im.width * scale, im.height * scale), Image.Resampling.NEAREST)
        canvas = Image.new("RGBA", (big.width + 40, big.height + 80), (32, 32, 40, 255))
        canvas.paste(big, (20, 40), big)
        # crosshair
        from PIL import ImageDraw, ImageFont
        d = ImageDraw.Draw(canvas)
        cx, cy = 20 + big.width // 2, 40 + big.height // 2
        d.line([(cx, 40), (cx, 40 + big.height)], fill=(0, 255, 0, 160), width=1)
        d.line([(20, cy), (20 + big.width, cy)], fill=(0, 255, 0, 160), width=1)
        d.text((8, 8), f"{label} icon QA (68px @4x + crosshair)", fill=(220, 220, 220, 255))
        canvas.save(outp)
        print(f"  wrote {outp}")

    print("3) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    icons = next(t for t in data["targets"] if t["name"] == "Icons")

    print("4) Fix Create icons: 20-a-fake20 -> 20-a")
    fix_create_icons_fake20(icons)

    print("5) Assign Icons 20-a/b/c")
    assign_triplet(icons, "20", black_pngs, assets)
    print("6) Replace fake20 costume assets with Phase 1 PNGs")
    also_replace_fake20_assets(icons, black_pngs, assets)

    print("7) Assign Icons 14-a/b/c")
    assign_triplet(icons, "14", simon_pngs, assets)

    print("8) Write sb3")
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

    # Verify extract
    print("9) Verify embedded costumes")
    with zipfile.ZipFile(SB3, "r") as z:
        data2 = json.loads(z.read("project.json"))
        icons2 = next(t for t in data2["targets"] if t["name"] == "Icons")
        # script check
        raw = json.dumps(icons2["blocks"])
        assert "20-a-fake20" not in raw or raw.count("20-a-fake20") == 0
        # Actually costume NAMES still include fake20; script fields should not
        for bid, b in icons2["blocks"].items():
            if isinstance(b, dict) and b.get("opcode") == "looks_costume":
                cost = (b.get("fields") or {}).get("COSTUME", [None])[0]
                if cost and "fake20" in str(cost):
                    raise RuntimeError(f"still switching to {cost}")
        for name in ("20-a", "20-b", "20-c", "14-a", "14-b", "14-c", "20-a-fake20"):
            c = next(x for x in icons2["costumes"] if x["name"] == name)
            blob = z.read(c["md5ext"])
            im = Image.open(io.BytesIO(blob))
            print(f"  {name}: {c['md5ext'][:12]}… {im.size} br={c.get('bitmapResolution')} fmt={c.get('dataFormat')}")
            # save extracted verify copies
            if name == "20-a":
                im.save(PREV / "verify-extracted-20a.png")
            if name == "14-a":
                im.save(PREV / "verify-extracted-14a.png")
            if name == "20-a-fake20":
                assert c["dataFormat"] == "png", "fake20 should now be png"
    print("DONE")


if __name__ == "__main__":
    main()

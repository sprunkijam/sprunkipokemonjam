#!/usr/bin/env python3
"""Add Mr. Sun Phase 1 art + Icons 11-* + sticky Phase 2 (b3 from stock horror)."""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_phase2_sticky import (  # noqa: E402
    append_sticky_forever,
    ensure_phase2_prefix,
    knock_black_bg,
    png_asset,
    rebuild_switch_costume,
    set_costume_png,
)
from strengthen_outlines import strengthen_outlines  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
ART_P1 = ROOT / "art" / "mrsun-phase1.png"
SRC_P1 = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments/"
    "0e33eb8228f54064fca7c5c65be96b629529226f1e949a47715e1d1a21bddf87.png"
)

SPRITE = "Mr. Sun"
POLO_ID = "-`_0:s3eXB|xF`[tz(`S"
ICON_NAMES = ("11-a", "11-b", "11-c")


def make_face_icons(phase1: Image.Image) -> dict[str, bytes]:
    """Face-zoom crop for shelf icons 11-a/b/c — round face + forehead gem + mane."""
    w, h = phase1.size
    # Upper-centered face: eyes, gem, cheek blush, jagged mane
    side = min(220, w, h)
    top = 8
    left = max(0, (w - side) // 2)
    if left + side > w:
        left = max(0, w - side)
    if top + side > h:
        top = max(0, h - side)
    face = phase1.crop((left, top, left + side, top + side))
    out: dict[str, bytes] = {}
    for name, size in (("11-a", 68), ("11-b", 70), ("11-c", 68)):
        im = face.resize((size, size), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        out[name] = buf.getvalue()
        print(f"  icon {name} {im.size} crop=({left},{top},{side})")
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
            print(f"  costume {name} -> phase1 {md5ext} cx={cx} cy={cy}")
        else:
            print(f"  costume {name} left untouched ({c.get('md5ext')})")


def ensure_b3_from_horror(target: dict) -> None:
    """Insert b3 pointing at existing anim??? asset so sticky Phase 2 works."""
    names = [c["name"] for c in target["costumes"]]
    if "b3" in names:
        print("  b3 already present")
        return
    horror = next((c for c in target["costumes"] if c["name"] == "anim???"), None)
    if horror is None:
        raise RuntimeError("no anim??? to clone for b3")
    idx = names.index("idle2") + 1 if "idle2" in names else 2
    new_c = {k: horror[k] for k in horror}
    new_c["name"] = "b3"
    target["costumes"].insert(idx, new_c)
    print(f"  inserted b3 at {idx} from anim??? -> {new_c.get('md5ext')}")


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
    print("1) Process Mr. Sun Phase 1 PNG (black→transparent, keep outlines)")
    raw = Image.open(SRC_P1)
    print(f"  src {raw.size} {raw.mode}")
    p1 = knock_black_bg(raw)
    print(f"  keyed {p1.size}")
    # backup pre-outline for idempotent re-strengthen
    bak_dir = ROOT / "art" / "_backup"
    bak_dir.mkdir(parents=True, exist_ok=True)
    p1.save(bak_dir / "mrsun-phase1.png", "PNG")
    p1 = strengthen_outlines(p1, mode="heavy_wide")
    ART_P1.parent.mkdir(parents=True, exist_ok=True)
    p1.save(ART_P1, "PNG")
    p1_bytes = ART_P1.read_bytes()
    print(f"  saved {ART_P1.name} {p1.size} ({len(p1_bytes)} bytes)")

    prev = ROOT / "art" / "_preview"
    prev.mkdir(exist_ok=True)
    bg = Image.new("RGBA", (p1.width + 20, p1.height + 20), (40, 120, 180, 255))
    bg.paste(p1, (10, 10), p1)
    bg.save(prev / "mrsun-p1-final-on-sky.png")
    # also checker preview
    chk = Image.new("RGBA", p1.size, (0, 0, 0, 0))
    for y in range(0, p1.height, 16):
        for x in range(0, p1.width, 16):
            c = (200, 200, 200, 255) if ((x // 16) + (y // 16)) % 2 == 0 else (160, 160, 160, 255)
            for yy in range(y, min(y + 16, p1.height)):
                for xx in range(x, min(x + 16, p1.width)):
                    chk.putpixel((xx, yy), c)
    chk.paste(p1, (0, 0), p1)
    chk.save(prev / "mrsun-p1-checker.png")

    print("2) Face icons 11-a/b/c")
    icon_pngs = make_face_icons(p1)
    for name, blob in icon_pngs.items():
        Image.open(io.BytesIO(blob)).save(prev / f"mrsun-icon-{name}.png")

    print("3) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    simon = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    simon_size_before = simon.get("size")
    simon_cx_before = simon["costumes"][0].get("rotationCenterX")

    mrsun = next(t for t in data["targets"] if t["name"] == SPRITE)
    print("4) Assign Phase 1 costumes (leave ??? alone)")
    assign_phase1_body(mrsun, p1_bytes, assets)

    print("5) Ensure b3 from stock horror anim???")
    ensure_b3_from_horror(mrsun)

    print("6) Icons 11-a/b/c")
    assign_icons(data, icon_pngs, assets)

    print("7) Phase 2 sticky + Switch Costume guards")
    hat = ensure_phase2_prefix(mrsun)
    append_sticky_forever(mrsun, hat)
    rebuild_switch_costume(mrsun, POLO_ID)

    simon2 = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    assert simon2.get("size") == simon_size_before, (simon2.get("size"), simon_size_before)
    assert simon2["costumes"][0].get("rotationCenterX") == simon_cx_before
    print(f"  Simon still size={simon2.get('size')} cx={simon_cx_before} OK")

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
    print("DONE")


if __name__ == "__main__":
    main()

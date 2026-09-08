#!/usr/bin/env python3
"""Add Mr. Sun Phase 2 art to b3 + anim???*; heavy_wide outlines; sticky scripts."""
from __future__ import annotations

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
ART_P2 = ROOT / "art" / "mrsun-phase2.png"
SRC_P2 = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments/"
    "c9cfa19c8d9e210326e6c88a59d31e04e4ef8e21eafb8cc2b427ed0275fc9f05.png"
)
SPRITE = "Mr. Sun"
POLO_ID = "-`_0:s3eXB|xF`[tz(`S"


def assign_phase2(target: dict, p2_bytes: bytes, assets: dict) -> None:
    md5, md5ext, cx, cy = png_asset(p2_bytes)
    assets[md5ext] = p2_bytes
    for c in target["costumes"]:
        name = c["name"]
        if name == "b3" or "???" in name:
            set_costume_png(c, md5, md5ext, cx, cy)
            print(f"  costume {name} -> phase2 {md5ext} cx={cx} cy={cy}")
        else:
            print(f"  costume {name} keep {c.get('md5ext')}")


def main() -> None:
    print("1) Process Mr. Sun Phase 2 PNG (knock bg + heavy_wide)")
    raw = Image.open(SRC_P2)
    print(f"  src {raw.size} {raw.mode}")
    p2 = knock_black_bg(raw)
    bak = ROOT / "art" / "_backup"
    bak.mkdir(parents=True, exist_ok=True)
    p2.save(bak / "mrsun-phase2.png", "PNG")
    print(f"  keyed+scaled {p2.size} -> backup")
    p2 = strengthen_outlines(p2, mode="heavy_wide")
    ART_P2.parent.mkdir(parents=True, exist_ok=True)
    p2.save(ART_P2, "PNG")
    p2_bytes = ART_P2.read_bytes()
    print(f"  saved {ART_P2.name} {p2.size} ({len(p2_bytes)} bytes)")

    prev = ROOT / "art" / "_preview"
    prev.mkdir(exist_ok=True)
    bg = Image.new("RGBA", (p2.width + 20, p2.height + 20), (40, 120, 180, 255))
    bg.paste(p2, (10, 10), p2)
    bg.save(prev / "mrsun-p2-final-on-sky.png")

    print("2) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    simon = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    simon_size = simon.get("size")
    simon_cx = simon["costumes"][0].get("rotationCenterX")
    oren = next(t for t in data["targets"] if t["name"] == "Orange (Oren)")
    oren_md5 = oren["costumes"][0].get("md5ext")

    mrsun = next(t for t in data["targets"] if t["name"] == SPRITE)
    print("3) Assign Phase 2 to b3 + anim???*")
    assign_phase2(mrsun, p2_bytes, assets)

    print("4) Ensure sticky Phase 2 scripts")
    hat = ensure_phase2_prefix(mrsun)
    append_sticky_forever(mrsun, hat)
    rebuild_switch_costume(mrsun, POLO_ID)

    simon2 = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    assert simon2.get("size") == simon_size
    assert simon2["costumes"][0].get("rotationCenterX") == simon_cx
    oren2 = next(t for t in data["targets"] if t["name"] == "Orange (Oren)")
    assert oren2["costumes"][0].get("md5ext") == oren_md5
    print(f"  Simon size={simon_size} + Oren untouched OK")

    print("5) Write sb3")
    used: set[str] = set()
    for t in data["targets"]:
        for c in t.get("costumes", []):
            if c.get("md5ext"):
                used.add(c["md5ext"])
        for s in t.get("sounds", []):
            if s.get("md5ext"):
                used.add(s["md5ext"])
    new_assets = {k: v for k, v in assets.items() if k in used}

    buf = __import__("io").BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(data, separators=(",", ":")))
        for name, blob in sorted(new_assets.items()):
            z.writestr(name, blob)
    SB3.write_bytes(buf.getvalue())
    print(f"  wrote {SB3} ({SB3.stat().st_size} bytes)")
    print("DONE")


if __name__ == "__main__":
    main()

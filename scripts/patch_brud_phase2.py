#!/usr/bin/env python3
"""Add Brown (brud) Phase 2 art → b3 + anim???*; sticky Phase 2; size 55.
Icons 07 left as Phase 1 face (already live). Phase 1 body already live.
"""
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
    png_asset,
    rebuild_switch_costume,
    set_costume_png,
)

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
ART_P1 = ROOT / "art" / "brud-phase1.png"
ART_P2 = ROOT / "art" / "brud-phase2.png"
PREV = ROOT / "art" / "_preview"
OUT_CHECK = Path("/workspace/brud-p2-check.png")

SPRITE = "Brown (brud)"
POLO_ID = "9?YD7L}|g~A48+20.+3V"


def ensure_b3_from_horror(target: dict) -> None:
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


def assign_phase2(target: dict, p2: bytes, assets: dict) -> None:
    md2, ext2, cx2, cy2 = png_asset(p2)
    assets[ext2] = p2
    for c in target["costumes"]:
        name = c["name"]
        if name == "b3" or "???" in name:
            set_costume_png(c, md2, ext2, cx2, cy2)
            print(f"  costume {name} → phase2 {ext2}")
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
    assert ART_P2.exists(), ART_P2
    assert ART_P1.exists(), ART_P1

    print("1) Preview Phase 2")
    p2_im = Image.open(ART_P2).convert("RGBA")
    print(f"  {ART_P2.name} {p2_im.size}")
    chk = checker(p2_im)
    chk.save(PREV / "brud-phase2-checker.png")
    chk.save(OUT_CHECK)
    print(f"  wrote {OUT_CHECK}")

    print("2) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    target = next(t for t in data["targets"] if t["name"] == SPRITE)
    print(f"3) Brud size={target.get('size')} → 55")
    target["size"] = 55.0

    print("4) Ensure b3 + assign Phase 2 to b3/anim???*")
    ensure_b3_from_horror(target)
    assign_phase2(target, ART_P2.read_bytes(), assets)

    print("5) Icons 07 left as Phase 1 (no change)")
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
    for c in icons["costumes"]:
        if c["name"].startswith("07"):
            print(f"  Icons {c['name']} keep {c.get('md5ext')} fmt={c.get('dataFormat')}")

    print("6) Phase 2 sticky + Switch Costume guards")
    hat = ensure_phase2_prefix(target)
    append_sticky_forever(target, hat)
    rebuild_switch_costume(target, POLO_ID)

    print("7) Write sb3")
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

    with zipfile.ZipFile(SB3, "r") as z:
        data2 = json.loads(z.read("project.json"))
    brud = next(t for t in data2["targets"] if t["name"] == SPRITE)
    print("VERIFY size", brud.get("size"))
    p1_md = None
    p2_md = None
    for c in brud["costumes"]:
        print(
            f"  {c['name']}: {c.get('md5ext')} br={c.get('bitmapResolution')} "
            f"fmt={c.get('dataFormat')}"
        )
        if c["name"] == "idle":
            p1_md = c.get("md5ext")
        if c["name"] == "b3":
            p2_md = c.get("md5ext")
    assert p1_md and p2_md and p1_md != p2_md, (p1_md, p2_md)
    ic = next(t for t in data2["targets"] if t["name"] == "Icons")
    for c in ic["costumes"]:
        if c["name"].startswith("07"):
            print(
                f"  Icons {c['name']}: {c.get('md5ext')} fmt={c.get('dataFormat')} "
                f"br={c.get('bitmapResolution')}"
            )
    print("DONE")


if __name__ == "__main__":
    main()

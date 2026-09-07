#!/usr/bin/env python3
"""Replace Red (Raddy) Phase 1 body + Icons 02-* + sticky Phase 2 scripts."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

from PIL import Image

# Reuse helpers from phase2 sticky patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_phase2_sticky import (  # noqa: E402
    TARGET_H,
    append_sticky_forever,
    ensure_phase2_prefix,
    knock_black_bg,
    png_asset,
    rebuild_switch_costume,
    set_costume_png,
)

ROOT = Path("/workspace/sprunkipokemonjam")
SB3 = ROOT / "sprunki-base.sb3"
ART_P1 = ROOT / "art" / "raddy-phase1.png"
SRC_P1 = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments/"
    "94c0e21de98106291bb1baa3394631c00f09616314b424e0964cee1c4e06dc7d.png"
)

SPRITE = "Red (Raddy)"
POLO_ID = "`Xsm{Rz6z,?ETGc^+F`}"
ICON_NAMES = ("02-a", "02-b", "02-c")


def make_face_icons(phase1: Image.Image) -> dict[str, bytes]:
    w, h = phase1.size
    side = 250
    top = 20
    left = (w - side) // 2
    face = phase1.crop((left, top, left + side, top + side))
    out: dict[str, bytes] = {}
    for name, size in (("02-a", 68), ("02-b", 70), ("02-c", 68)):
        im = face.resize((size, size), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        out[name] = buf.getvalue()
        print(f"  icon {name} {im.size}")
    return out


def assign_phase1_body(target: dict, p1_bytes: bytes, assets: dict) -> None:
    md5, md5ext, cx, cy = png_asset(p1_bytes)
    assets[md5ext] = p1_bytes
    for c in target["costumes"]:
        name = c["name"]
        # Phase 1 only: idle/idle2/anim* without ???
        if name in ("idle", "idle2") or (
            name.startswith("anim") and "???" not in name
        ):
            set_costume_png(c, md5, md5ext, cx, cy)
            print(f"  costume {name} → phase1 {md5ext}")
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
    print(f"  inserted b3 at {idx} from anim??? → {new_c.get('md5ext')}")


def assign_icons(data: dict, icon_pngs: dict[str, bytes], assets: dict) -> None:
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
    for c in icons["costumes"]:
        if c["name"] not in icon_pngs:
            continue
        blob = icon_pngs[c["name"]]
        md5, md5ext, cx, cy = png_asset(blob)
        assets[md5ext] = blob
        set_costume_png(c, md5, md5ext, cx, cy)
        print(f"  Icons {c['name']} → {md5ext} {Image.open(io.BytesIO(blob)).size}")


def main() -> None:
    print("1) Process Raddy Phase 1 PNG")
    p1 = knock_black_bg(Image.open(SRC_P1))
    ART_P1.parent.mkdir(parents=True, exist_ok=True)
    p1.save(ART_P1, "PNG")
    p1_bytes = ART_P1.read_bytes()
    print(f"  {ART_P1.name} {p1.size} ({len(p1_bytes)} bytes)")

    print("2) Face icons")
    icon_pngs = make_face_icons(p1)

    print("3) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    raddy = next(t for t in data["targets"] if t["name"] == SPRITE)
    print("4) Assign Phase 1 costumes (leave ??? alone)")
    assign_phase1_body(raddy, p1_bytes, assets)

    print("5) Ensure b3 from stock horror anim???")
    ensure_b3_from_horror(raddy)

    print("6) Icons 02-a/b/c")
    assign_icons(data, icon_pngs, assets)

    print("7) Phase 2 sticky + Switch Costume guards")
    hat = ensure_phase2_prefix(raddy)
    append_sticky_forever(raddy, hat)
    rebuild_switch_costume(raddy, POLO_ID)

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

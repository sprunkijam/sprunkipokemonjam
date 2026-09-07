#!/usr/bin/env python3
"""Replace Green (Vineria) Phase 1 body + Icons 05-* + sticky Phase 2 scripts."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from PIL import Image

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_phase2_sticky import (  # noqa: E402
    append_sticky_forever,
    ensure_phase2_prefix,
    knock_black_bg,
    png_asset,
    rebuild_switch_costume,
    set_costume_png,
)

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
ART_P1 = ROOT / "art" / "vineria-phase1.png"
SRC_P1 = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments/"
    "90de50ffbbd4d8ad9f11aaa3a4670591c76af5313479088221c4e0fd9ffe8272.png"
)

SPRITE = "Green (Vineria)"
POLO_ID = "ur?}lr(ey-KrLsfs,`X#"
ICON_NAMES = ("05-a", "05-b", "05-c")


def make_face_icons(phase1: Image.Image) -> dict[str, bytes]:
    """Face-zoom crop for shelf icons 05-a/b/c."""
    w, h = phase1.size
    # Tuned for Vineria: leaves+ears+face (upper portion, slightly left of center)
    side = min(240, w, h)
    top = 8
    # face sits left-of-center in full sprite; bias crop left a bit
    left = max(0, (w // 2) - side // 2 - 20)
    if left + side > w:
        left = w - side
    face = phase1.crop((left, top, left + side, top + side))
    out: dict[str, bytes] = {}
    for name, size in (("05-a", 68), ("05-b", 70), ("05-c", 68)):
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
    print("1) Process Vineria Phase 1 PNG")
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

    # Sanity: do not touch Simon
    simon = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    simon_size_before = simon.get("size")
    simon_cx_before = simon["costumes"][0].get("rotationCenterX")

    vineria = next(t for t in data["targets"] if t["name"] == SPRITE)
    print("4) Assign Phase 1 costumes (leave ??? alone)")
    assign_phase1_body(vineria, p1_bytes, assets)

    print("5) Ensure b3 from stock horror anim???")
    ensure_b3_from_horror(vineria)

    print("6) Icons 05-a/b/c")
    assign_icons(data, icon_pngs, assets)

    print("7) Phase 2 sticky + Switch Costume guards")
    hat = ensure_phase2_prefix(vineria)
    append_sticky_forever(vineria, hat)
    rebuild_switch_costume(vineria, POLO_ID)

    # Verify Simon untouched
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

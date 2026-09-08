#!/usr/bin/env python3
"""Add Mr. Fun Computer Phase 1/2 art, Icons 16 face zooms, sticky Phase 2."""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _mrfun_pipeline import process_mrfun  # noqa: E402
from patch_phase2_sticky import (  # noqa: E402
    append_sticky_forever,
    ensure_phase2_prefix,
    png_asset,
    rebuild_switch_costume,
    set_costume_png,
)

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
ART_P1 = ROOT / "art" / "mrfuncomputer-phase1.png"
ART_P2 = ROOT / "art" / "mrfuncomputer-phase2.png"
SRC_P1 = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments/"
    "7fee04b4ee95db68434537d9654351be198e37f6009d1ee711959d55942023ba.png"
)
SRC_P2 = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments/"
    "6cb848078c92502d16aa751ff8b347c95b428aa3332caaa5a4abef9751ff59eb.png"
)
PREV = ROOT / "art" / "_preview"
OUT_CHECK = Path("/workspace/mrfuncomputer-p1-check.png")

SPRITE = "Mr. Fun Computer"
POLO_ID = "Pja@`rOFl1)xdb:X7}9$"
ICON_SLOT = "16"
# Face-centered crop on phase1 (260x400): monitor screen + propeller hat
ICON_LEFT, ICON_TOP, ICON_SIDE = 36, 39, 160


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


def assign_body(target: dict, p1: bytes, p2: bytes, assets: dict) -> None:
    md1, ext1, cx1, cy1 = png_asset(p1)
    md2, ext2, cx2, cy2 = png_asset(p2)
    assets[ext1] = p1
    assets[ext2] = p2
    for c in target["costumes"]:
        name = c["name"]
        if name == "b3" or "???" in name:
            set_costume_png(c, md2, ext2, cx2, cy2)
            print(f"  costume {name} → phase2 {ext2}")
        elif name in ("idle", "idle2") or (
            name.startswith("anim") and "???" not in name
        ):
            set_costume_png(c, md1, ext1, cx1, cy1)
            print(f"  costume {name} → phase1 {ext1}")
        else:
            print(f"  costume {name} left ({c.get('md5ext')})")


def assign_icons(data: dict, icon_pngs: dict[str, bytes], assets: dict) -> None:
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
    for c in icons["costumes"]:
        if c["name"] not in icon_pngs:
            continue
        blob = icon_pngs[c["name"]]
        md5, md5ext, cx, cy = png_asset(blob)
        assets[md5ext] = blob
        set_costume_png(c, md5, md5ext, cx, cy)
        print(f"  Icons {c['name']} → {md5ext} {Image.open(io.BytesIO(blob)).size} br=2")


def fix_fake16_refs(icons: dict) -> int:
    """Retarget any fake16 hard-switches to real 16-* PNG costumes."""
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
        name = costume[0]
        if "fake" in name.lower() and str(name).startswith("16"):
            base = name.split("-fake")[0]
            if not base.startswith("16"):
                base = "16-a"
            print(f"  retarget looks_costume {bid}: {name} -> {base}")
            fields["COSTUME"] = [base, None]
            fixed += 1
    return fixed


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
    orig = ROOT / "art" / "_originals"
    orig.mkdir(parents=True, exist_ok=True)

    print("1) Process Phase 1/2 PNGs (light-gray keep-mask)")
    assert SRC_P1.exists(), SRC_P1
    assert SRC_P2.exists(), SRC_P2
    Image.open(SRC_P1).save(orig / "mrfuncomputer-phase1-src.png")
    Image.open(SRC_P2).save(orig / "mrfuncomputer-phase2-src.png")

    p1 = process_mrfun(Image.open(SRC_P1), knock_floor_puddle=False)
    p2 = process_mrfun(Image.open(SRC_P2), knock_floor_puddle=True)
    ART_P1.parent.mkdir(parents=True, exist_ok=True)
    p1.save(ART_P1, "PNG")
    p2.save(ART_P2, "PNG")
    print(f"  saved {ART_P1.name} {p1.size} ({ART_P1.stat().st_size} bytes)")
    print(f"  saved {ART_P2.name} {p2.size} ({ART_P2.stat().st_size} bytes)")

    checker(p1).save(PREV / "mrfuncomputer-phase1-checker.png")
    checker(p2).save(PREV / "mrfuncomputer-phase2-checker.png")
    checker(p1).save(OUT_CHECK)
    print(f"  wrote {OUT_CHECK}")

    print("2) Face icons 16-a/b/c from Phase 1 monitor face")
    icon_pngs = make_face_icons(p1)
    for name, blob in icon_pngs.items():
        Image.open(io.BytesIO(blob)).save(PREV / f"mrfun-icon-{name}.png")

    print("3) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    target = next(t for t in data["targets"] if t["name"] == SPRITE)
    print(f"4) Size keep ~55 (stock={target.get('size')})")
    target["size"] = 55.0

    print("5) Ensure b3 + assign Phase 1/2 costumes")
    ensure_b3_from_horror(target)
    # After ensure_b3, re-assign so b3 gets phase2 (ensure clones horror asset first)
    assign_body(target, ART_P1.read_bytes(), ART_P2.read_bytes(), assets)

    print("6) Icons 16-* (Create icons slot 16 = Mr. Fun Computer)")
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
    fixed = fix_fake16_refs(icons)
    print(f"  fake16 retargets: {fixed}")
    assign_icons(data, icon_pngs, assets)
    # Replace any 16-*-fake* costume assets if present
    for c in icons["costumes"]:
        if c["name"].startswith("16") and "fake" in c["name"].lower():
            suffix = "a"
            if "-b" in c["name"]:
                suffix = "b"
            elif "-c" in c["name"]:
                suffix = "c"
            key = f"{ICON_SLOT}-{suffix}"
            if key in icon_pngs:
                blob = icon_pngs[key]
                md5, md5ext, cx, cy = png_asset(blob)
                assets[md5ext] = blob
                set_costume_png(c, md5, md5ext, cx, cy)
                print(f"  Icons {c['name']} asset → {md5ext} (name kept)")

    print("7) Phase 2 sticky + Switch Costume guards")
    hat = ensure_phase2_prefix(target)
    append_sticky_forever(target, hat)
    rebuild_switch_costume(target, POLO_ID)

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

    with zipfile.ZipFile(SB3, "r") as z:
        data2 = json.loads(z.read("project.json"))
    mfc = next(t for t in data2["targets"] if t["name"] == SPRITE)
    print("VERIFY size", mfc.get("size"))
    print("VERIFY costumes:")
    for c in mfc["costumes"]:
        if c["name"] in ("idle", "idle2", "b3", "anim", "anim???") or c["name"].startswith(
            "anim"
        ):
            print(
                f"  {c['name']}: {c.get('md5ext')} br={c.get('bitmapResolution')} "
                f"fmt={c.get('dataFormat')}"
            )
    ic = next(t for t in data2["targets"] if t["name"] == "Icons")
    for c in ic["costumes"]:
        if c["name"].startswith("16"):
            print(
                f"  Icons {c['name']}: {c.get('md5ext')} fmt={c.get('dataFormat')} "
                f"br={c.get('bitmapResolution')}"
            )
    print("DONE")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Add Silver (Clukr) Phase 1/2 art, Icons 03 face zooms, sticky Phase 2.

Wide 3-sphere canvas → size ~40 (Fun Bot Magnemite / Oren visual scale).
"""
from __future__ import annotations

import hashlib
import io
import json
import random
import string
import sys
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_phase2_sticky import (  # noqa: E402
    append_sticky_forever,
    ensure_phase2_prefix,
    rebuild_switch_costume,
)

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
ART_P1 = ROOT / "art" / "clukr-phase1.png"
ART_P2 = ROOT / "art" / "clukr-phase2.png"
PREV = ROOT / "art" / "_preview"
OUT_CHECK = Path("/workspace/clukr-p1-check.png")

SPRITE = "Silver (Clukr)"
ICON_SLOT = "03"
# Top-sphere face + cymbal on phase1 (403x400)
ICON_LEFT, ICON_TOP, ICON_SIDE = 110, 20, 180
POLO_ID = "}ygT1=Hr(YK,2q~D:Dp1"  # Polo Im On RN (value 3)
CLUKR_SIZE = 40.0


def uid(n: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "#%()*+,-./:;=?@[]^_{}~"
    return "".join(random.choice(alphabet) for _ in range(n))


def new_id(blocks: dict) -> str:
    for _ in range(80):
        i = uid()
        if i not in blocks:
            return i
    raise RuntimeError("id collision")


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
    print(f"  inserted b3 at {idx} from anim???")


def assign_bodies(target: dict, p1: bytes, p2: bytes, assets: dict) -> None:
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


def ensure_drop_size(target: dict, size: float) -> None:
    """Insert/update looks_setsizeto on Start Polo drop (b2 → show mh)."""
    blocks = target["blocks"]
    target["size"] = float(size)
    layer = blocks.get("b2")
    show = blocks.get("mh")
    if not layer or layer.get("opcode") != "looks_goforwardbackwardlayers":
        raise RuntimeError(f"expected b2 goforwardbackwardlayers, got {layer}")
    if not show or show.get("opcode") != "looks_show":
        raise RuntimeError(f"expected mh looks_show, got {show}")

    existing = [
        bid
        for bid, b in blocks.items()
        if isinstance(b, dict) and b.get("opcode") == "looks_setsizeto"
    ]
    if existing:
        for bid in existing:
            blocks[bid]["inputs"]["SIZE"] = [1, [4, str(int(size) if size == int(size) else size)]]
            print(f"  updated setsizeto {bid} → {size}")
        return

    if layer.get("next") == "mh":
        sid = new_id(blocks)
        blocks[sid] = {
            "opcode": "looks_setsizeto",
            "next": "mh",
            "parent": "b2",
            "inputs": {"SIZE": [1, [4, str(int(size))]]},
            "fields": {},
            "shadow": False,
            "topLevel": False,
        }
        layer["next"] = sid
        show["parent"] = sid
        print(f"  inserted setsizeto {sid} between b2 and mh → {size}")
    else:
        mid = layer.get("next")
        mb = blocks.get(mid) if mid else None
        if mb and mb.get("opcode") == "looks_setsizeto":
            mb["inputs"]["SIZE"] = [1, [4, str(int(size))]]
            print(f"  size block already in chain ({mid}) → {size}")
        else:
            raise RuntimeError(f"b2.next expected mh or setsizeto, got {mid}")


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
    assert ART_P2.exists(), ART_P2

    print("1) Face icons from Phase 1 (top sphere)")
    p1_im = Image.open(ART_P1).convert("RGBA")
    print(f"  source {ART_P1.name} {p1_im.size}")
    icon_pngs = make_face_icons(p1_im)
    Image.open(io.BytesIO(icon_pngs[f"{ICON_SLOT}-a"])).save(
        PREV / f"icon-new-{ICON_SLOT}a.png"
    )
    checker(p1_im).save(OUT_CHECK)
    print(f"  wrote {OUT_CHECK}")
    checker(Image.open(ART_P2).convert("RGBA")).save(PREV / "clukr-phase2-checker.png")

    print("2) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    target = next(t for t in data["targets"] if t["name"] == SPRITE)
    print(f"3) Clukr size={target.get('size')} → {CLUKR_SIZE} (wide 3-sphere)")
    ensure_drop_size(target, CLUKR_SIZE)

    print("4) Ensure b3 + assign Phase 1/2 costumes")
    ensure_b3_from_horror(target)
    assign_bodies(target, ART_P1.read_bytes(), ART_P2.read_bytes(), assets)

    print("5) Icons 03-* (Create slot; no fake* hard-switches)")
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
    # Retarget any fake03 if present
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
        if isinstance(name, str) and "fake" in name.lower() and name.startswith("03"):
            base = name.split("-fake")[0]
            print(f"  retarget looks_costume {bid}: {name} -> {base}")
            fields["COSTUME"] = [base, None]
            fixed += 1
    print(f"  fake03 retargets: {fixed}")

    for c in icons["costumes"]:
        if c["name"] not in icon_pngs:
            continue
        blob = icon_pngs[c["name"]]
        md5, md5ext, cx, cy = png_asset(blob)
        assets[md5ext] = blob
        set_costume_png(c, md5, md5ext, cx, cy)
        print(
            f"  Icons {c['name']} → {md5ext} "
            f"{Image.open(io.BytesIO(blob)).size} br=2"
        )

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
    print(f"wrote {SB3} ({SB3.stat().st_size} bytes)")

    with zipfile.ZipFile(SB3, "r") as z:
        data2 = json.loads(z.read("project.json"))
    cl = next(t for t in data2["targets"] if t["name"] == SPRITE)
    print("VERIFY Clukr size", cl.get("size"))
    p1_md = p2_md = None
    for c in cl["costumes"]:
        print(
            f"  {c['name']}: {c.get('md5ext')} br={c.get('bitmapResolution')} "
            f"fmt={c.get('dataFormat')}"
        )
        if c["name"] == "idle":
            p1_md = c.get("md5ext")
        if c["name"] == "b3":
            p2_md = c.get("md5ext")
    assert p1_md and p2_md and p1_md != p2_md, (p1_md, p2_md)
    sizes = [
        (bid, b["inputs"]["SIZE"])
        for bid, b in cl["blocks"].items()
        if isinstance(b, dict) and b.get("opcode") == "looks_setsizeto"
    ]
    print("VERIFY looks_setsizeto", sizes)
    ic = next(t for t in data2["targets"] if t["name"] == "Icons")
    for c in ic["costumes"]:
        if c["name"].startswith("03"):
            print(
                f"  Icons {c['name']}: {c.get('md5ext')} {c.get('dataFormat')} "
                f"br={c.get('bitmapResolution')}"
            )
    fb = next(t for t in data2["targets"] if t["name"] == "Fun Bot")
    print("VERIFY Fun Bot size unchanged", fb.get("size"))
    print("DONE")


if __name__ == "__main__":
    main()

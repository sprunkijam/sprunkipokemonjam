#!/usr/bin/env python3
"""Add Lime (OWAKCX) Phase 1 art + Icons 09 face zooms. Phase 2 not yet.

Wide DJ-deck canvas → size 50 (Gray DJ peer; Fun Bot/Clukr used 40 for wider).
"""
from __future__ import annotations

import hashlib
import io
import json
import random
import string
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
ART_P1 = ROOT / "art" / "owakcx-phase1.png"
PREV = ROOT / "art" / "_preview"
OUT_CHECK = Path("/workspace/owakcx-p1-check.png")

SPRITE = "Lime (OWAKCX)"
ICON_SLOT = "09"
# Face crop on phase1 (310x400): spiky hair + eyes + open mouth/tongue
ICON_LEFT, ICON_TOP, ICON_SIDE = 40, 20, 180
OWAKCX_SIZE = 50.0
# Start Polo drop: goforwardbackwardlayers cN → looks_show nO
LAYER_ID = "cN"
SHOW_ID = "nO"


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


def ensure_drop_size(target: dict, size: float) -> None:
    """Insert/update looks_setsizeto on Start Polo drop (cN → show nO)."""
    blocks = target["blocks"]
    target["size"] = float(size)
    layer = blocks.get(LAYER_ID)
    show = blocks.get(SHOW_ID)
    if not layer or layer.get("opcode") != "looks_goforwardbackwardlayers":
        raise RuntimeError(f"expected {LAYER_ID} goforwardbackwardlayers, got {layer}")
    if not show or show.get("opcode") != "looks_show":
        raise RuntimeError(f"expected {SHOW_ID} looks_show, got {show}")

    size_str = str(int(size) if size == int(size) else size)
    existing = [
        bid
        for bid, b in blocks.items()
        if isinstance(b, dict) and b.get("opcode") == "looks_setsizeto"
    ]
    if existing:
        for bid in existing:
            blocks[bid]["inputs"]["SIZE"] = [1, [4, size_str]]
            print(f"  updated setsizeto {bid} → {size}")
        return

    if layer.get("next") == SHOW_ID:
        sid = new_id(blocks)
        blocks[sid] = {
            "opcode": "looks_setsizeto",
            "next": SHOW_ID,
            "parent": LAYER_ID,
            "inputs": {"SIZE": [1, [4, size_str]]},
            "fields": {},
            "shadow": False,
            "topLevel": False,
        }
        layer["next"] = sid
        show["parent"] = sid
        print(f"  inserted setsizeto {sid} between {LAYER_ID} and {SHOW_ID} → {size}")
    else:
        mid = layer.get("next")
        mb = blocks.get(mid) if mid else None
        if mb and mb.get("opcode") == "looks_setsizeto":
            mb["inputs"]["SIZE"] = [1, [4, size_str]]
            print(f"  size block already in chain ({mid}) → {size}")
        else:
            raise RuntimeError(f"{LAYER_ID}.next expected {SHOW_ID} or setsizeto, got {mid}")


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

    print("1) Face icons from Phase 1 (hair+eyes+mouth)")
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
    print(f"3) OWAKCX size={target.get('size')} → {OWAKCX_SIZE} (wide DJ deck)")
    ensure_drop_size(target, OWAKCX_SIZE)

    print("4) Assign Phase 1 costumes (idle/idle2/non-??? anim*)")
    assign_phase1_body(target, ART_P1.read_bytes(), assets)

    print("5) Icons 09-* (Create slot; no fake* hard-switches)")
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
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
        if isinstance(name, str) and "fake" in name.lower() and name.startswith("09"):
            base = name.split("-fake")[0]
            print(f"  retarget looks_costume {bid}: {name} -> {base}")
            fields["COSTUME"] = [base, None]
            fixed += 1
    print(f"  fake09 retargets: {fixed}")

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
    ow = next(t for t in data2["targets"] if t["name"] == SPRITE)
    print("VERIFY OWAKCX size", ow.get("size"))
    p1_md = None
    for c in ow["costumes"]:
        print(
            f"  {c['name']}: {c.get('md5ext')} br={c.get('bitmapResolution')} "
            f"fmt={c.get('dataFormat')}"
        )
        if c["name"] == "idle":
            p1_md = c.get("md5ext")
    assert p1_md and p1_md.endswith(".png"), p1_md
    # ??? costumes still svg/old
    horror = [c for c in ow["costumes"] if "???" in c["name"]]
    assert horror and horror[0].get("md5ext") != p1_md
    sizes = [
        (bid, b["inputs"]["SIZE"])
        for bid, b in ow["blocks"].items()
        if isinstance(b, dict) and b.get("opcode") == "looks_setsizeto"
    ]
    print("VERIFY looks_setsizeto", sizes)
    ic = next(t for t in data2["targets"] if t["name"] == "Icons")
    for c in ic["costumes"]:
        if c["name"].startswith("09"):
            print(
                f"  Icons {c['name']}: {c.get('md5ext')} {c.get('dataFormat')} "
                f"br={c.get('bitmapResolution')}"
            )
    fb = next(t for t in data2["targets"] if t["name"] == "Fun Bot")
    print("VERIFY Fun Bot size unchanged", fb.get("size"))
    print("DONE")


if __name__ == "__main__":
    main()

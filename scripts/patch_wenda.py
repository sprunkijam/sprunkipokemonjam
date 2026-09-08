#!/usr/bin/env python3
"""Add White (Wenda) Phase 1/2 art, Icons 17 face zooms, sticky Phase 2."""
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
ART_P1 = ROOT / "art" / "wenda-phase1.png"
ART_P2 = ROOT / "art" / "wenda-phase2.png"
PREV = ROOT / "art" / "_preview"
OUT_CHECK = Path("/workspace/wenda-p1-check.png")

SPRITE = "White (Wenda)"
ICON_SLOT = "17"
# Face-centered crop on phase1 (249x400): ears + eyes + gem + chin paw
ICON_LEFT, ICON_TOP, ICON_SIDE = 25, 8, 190
BROADCAST_PHASE2 = ["Phase 2", "2qOY4J,K81HY:t`XJFlx"]


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


def make_switch_to_b3(blocks: dict, parent: str | None) -> str:
    stmt = new_id(blocks)
    menu = new_id(blocks)
    blocks[menu] = {
        "opcode": "looks_costume",
        "next": None,
        "parent": stmt,
        "inputs": {},
        "fields": {"COSTUME": ["b3", None]},
        "shadow": True,
        "topLevel": False,
    }
    blocks[stmt] = {
        "opcode": "looks_switchcostumeto",
        "next": None,
        "parent": parent,
        "inputs": {"COSTUME": [1, menu]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    return stmt


def make_stop_other(blocks: dict, parent: str | None) -> str:
    stmt = new_id(blocks)
    blocks[stmt] = {
        "opcode": "control_stop",
        "next": None,
        "parent": parent,
        "inputs": {},
        "fields": {"STOP_OPTION": ["other scripts in sprite", None]},
        "shadow": False,
        "topLevel": False,
        "mutation": {
            "tagName": "mutation",
            "children": [],
            "hasnext": "true",
        },
    }
    return stmt


def make_phase_eq_2(blocks: dict, parent: str) -> str:
    eq = new_id(blocks)
    blocks[eq] = {
        "opcode": "operator_equals",
        "next": None,
        "parent": parent,
        "inputs": {
            "OPERAND1": [3, [12, "Phase", "Phase"], [10, ""]],
            "OPERAND2": [1, [10, "2"]],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    return eq


def make_wait0(blocks: dict, parent: str) -> str:
    stmt = new_id(blocks)
    blocks[stmt] = {
        "opcode": "control_wait",
        "next": None,
        "parent": parent,
        "inputs": {"DURATION": [1, [4, "0"]]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    return stmt


def ensure_b3_costume(target: dict) -> None:
    names = [c["name"] for c in target["costumes"]]
    if "b3" in names:
        print("  b3 already present")
        return
    template = next(
        (c for c in target["costumes"] if c["name"] == "anim???"),
        next(c for c in target["costumes"] if c["name"] == "idle"),
    )
    insert_at = names.index("idle2") + 1 if "idle2" in names else 2
    new_c = dict(template)
    new_c["name"] = "b3"
    target["costumes"].insert(insert_at, new_c)
    print(f"  inserted b3 at {insert_at} from {template['name']}")


def ensure_phase2_sticky(target: dict) -> None:
    blocks = target["blocks"]
    hat_id = None
    for bid, b in blocks.items():
        if not isinstance(b, dict):
            continue
        if b.get("opcode") != "event_whenbroadcastreceived":
            continue
        opt = (b.get("fields") or {}).get("BROADCAST_OPTION")
        if opt and opt[0] == "Phase 2":
            hat_id = bid
            break
    if hat_id is None:
        hat_id = new_id(blocks)
        blocks[hat_id] = {
            "opcode": "event_whenbroadcastreceived",
            "next": None,
            "parent": None,
            "inputs": {},
            "fields": {"BROADCAST_OPTION": BROADCAST_PHASE2},
            "shadow": False,
            "topLevel": True,
            "x": 100,
            "y": 100,
        }
        print("  created Phase 2 hat")

    hat = blocks[hat_id]
    nxt = hat.get("next")
    already_prefix = False
    if nxt and isinstance(blocks.get(nxt), dict):
        nb = blocks[nxt]
        if nb.get("opcode") == "looks_switchcostumeto":
            cin = nb.get("inputs", {}).get("COSTUME")
            if isinstance(cin, list) and len(cin) >= 2 and isinstance(cin[1], str):
                menu = blocks.get(cin[1])
                if (
                    isinstance(menu, dict)
                    and (menu.get("fields") or {}).get("COSTUME", [None])[0] == "b3"
                ):
                    stop = nb.get("next")
                    if (
                        stop
                        and isinstance(blocks.get(stop), dict)
                        and blocks[stop].get("opcode") == "control_stop"
                    ):
                        already_prefix = True
    if not already_prefix:
        old_next = hat.get("next")
        switch_id = make_switch_to_b3(blocks, hat_id)
        stop_id = make_stop_other(blocks, switch_id)
        blocks[switch_id]["next"] = stop_id
        blocks[stop_id]["next"] = old_next
        hat["next"] = switch_id
        if old_next and old_next in blocks and isinstance(blocks[old_next], dict):
            blocks[old_next]["parent"] = stop_id
        print("  Phase 2 → switch b3 → stop others")
    else:
        print("  Phase 2 prefix OK")

    cur = hat_id
    seen: set[str] = set()
    last = hat_id
    while cur and cur not in seen:
        seen.add(cur)
        b = blocks[cur]
        if not isinstance(b, dict):
            break
        if b.get("opcode") == "control_forever":
            print("  sticky forever already present")
            return
        last = cur
        cur = b.get("next")

    forever_id = new_id(blocks)
    if_id = new_id(blocks)
    eq_id = make_phase_eq_2(blocks, if_id)
    switch_id = make_switch_to_b3(blocks, if_id)
    wait_id = make_wait0(blocks, forever_id)
    blocks[if_id] = {
        "opcode": "control_if",
        "next": wait_id,
        "parent": forever_id,
        "inputs": {"CONDITION": [2, eq_id], "SUBSTACK": [2, switch_id]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    blocks[forever_id] = {
        "opcode": "control_forever",
        "next": None,
        "parent": last if last != hat_id else hat_id,
        "inputs": {"SUBSTACK": [2, if_id]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    blocks[last]["next"] = forever_id
    print("  appended sticky forever")


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


def fix_fake17_refs(icons: dict) -> int:
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
        if "fake" in name.lower() and "17" in name:
            base = name.split("-fake")[0]
            if not base.startswith("17"):
                base = "17-a"
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
    assert ART_P1.exists(), ART_P1
    assert ART_P2.exists(), ART_P2

    print("1) Face icons from Phase 1")
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
    print(f"3) Wenda size={target.get('size')} → 55")
    target["size"] = 55.0

    print("4) Ensure b3 + sticky Phase 2")
    ensure_b3_costume(target)
    ensure_phase2_sticky(target)

    print("5) Assign Phase 1/2 costumes")
    assign_body(target, ART_P1.read_bytes(), ART_P2.read_bytes(), assets)

    print("6) Icons 17-*")
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
    fixed = fix_fake17_refs(icons)
    print(f"  fake17 retargets: {fixed}")
    for c in icons["costumes"]:
        if c["name"] not in icon_pngs:
            continue
        blob = icon_pngs[c["name"]]
        md5, md5ext, cx, cy = png_asset(blob)
        assets[md5ext] = blob
        set_costume_png(c, md5, md5ext, cx, cy)
        print(f"  Icons {c['name']} → {md5ext} {Image.open(io.BytesIO(blob)).size}")

    for c in icons["costumes"]:
        if c["name"].startswith("17") and "fake" in c["name"].lower():
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
    wenda = next(t for t in data2["targets"] if t["name"] == SPRITE)
    print("VERIFY Wenda size", wenda.get("size"))
    print("VERIFY costumes:")
    for c in wenda["costumes"]:
        print(f"  {c['name']}: {c.get('md5ext')} br={c.get('bitmapResolution')}")
    ic = next(t for t in data2["targets"] if t["name"] == "Icons")
    for c in ic["costumes"]:
        if c["name"].startswith("17"):
            print(f"  Icons {c['name']}: {c.get('md5ext')} {c.get('dataFormat')} br={c.get('bitmapResolution')}")


if __name__ == "__main__":
    main()

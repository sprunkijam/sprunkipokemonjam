#!/usr/bin/env python3
"""Replace Pink (Pinki) Phase 1/2 art + Icons 18-* + Phase 2 instant-swap."""
from __future__ import annotations

import hashlib
import io
import json
import random
import string
import zipfile
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path("/workspace/sprunkipokemonjam")
SB3 = ROOT / "sprunki-base.sb3"
ART_P1 = ROOT / "art" / "pinki-phase1.png"
ART_P2 = ROOT / "art" / "pinki-phase2.png"
SRC_P1 = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments/"
    "67eec4cdf12d3cdfd56fe7ea37db57d2a726704afac0387165b6790da7ce5b45.png"
)
SRC_P2 = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments/"
    "a0a04c327f50ac11bd00822628a6a4aba03bc365d54c1b43057a904fa1a7303b.png"
)

TARGET_H = 400
PHASE1_NAMES = None  # filled after load: non-??? costumes except b3
PHASE2_NAMES = None

SPRITE = "Pink (Pinki)"


def knock_black_bg(im: Image.Image, thresh: int = 35) -> Image.Image:
    """Corner/edge flood-fill near-black → transparent; keep enclosed dark mouths."""
    arr = np.array(im.convert("RGBA"))
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3].astype(np.int16)
    a = arr[:, :, 3]
    mx = rgb.max(axis=2)
    is_black = (mx <= thresh) & (a > 0)
    is_empty = a == 0
    knock = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    ys, xs = np.where(is_empty)
    for y, x in zip(ys.tolist(), xs.tolist()):
        knock[y, x] = True
        q.append((y, x))
    for x in range(w):
        for y in (0, h - 1):
            if (is_black[y, x] or is_empty[y, x]) and not knock[y, x]:
                knock[y, x] = True
                q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if (is_black[y, x] or is_empty[y, x]) and not knock[y, x]:
                knock[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not knock[ny, nx]:
                if is_black[ny, nx] or is_empty[ny, nx]:
                    knock[ny, nx] = True
                    q.append((ny, nx))
    out = arr.copy()
    out[knock & is_black, 3] = 0
    img = Image.fromarray(out, "RGBA")
    bbox = img.split()[-1].getbbox()
    if bbox:
        l, t, r, btm = bbox
        pad = 2
        l = max(0, l - pad)
        t = max(0, t - pad)
        r = min(img.width, r + pad)
        btm = min(img.height, btm + pad)
        img = img.crop((l, t, r, btm))
    if img.height != TARGET_H:
        nw = max(1, round(img.width * TARGET_H / img.height))
        img = img.resize((nw, TARGET_H), Image.Resampling.LANCZOS)
    return img


def make_face_icons(phase1: Image.Image) -> dict[str, bytes]:
    """Tight face crop → 18-a/c 68x68, 18-b 70x70 (matches Durple/Simon)."""
    w, h = phase1.size
    # Tuned on pinki-phase1: curl + eyes + mouth
    side = 210
    top = 25
    left = (w - side) // 2
    face = phase1.crop((left, top, left + side, top + side))
    out = {}
    for name, size in (("18-a", 68), ("18-b", 70), ("18-c", 68)):
        im = face.resize((size, size), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        out[name] = buf.getvalue()
        print(f"  icon {name} {im.size}")
    return out


def uid(n: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "#%()*+,-./:;=?@[]^_{}~"
    return "".join(random.choice(alphabet) for _ in range(n))


def new_id(blocks: dict) -> str:
    for _ in range(80):
        i = uid()
        if i not in blocks:
            return i
    raise RuntimeError("id collision")


def make_switch_to_b3(blocks: dict, parent: str | None) -> tuple[str, str]:
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
    return stmt, menu


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


def patch_phase2_handler(target: dict) -> None:
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
    if not hat_id:
        raise RuntimeError(f"No Phase 2 hat on {target['name']}")
    hat = blocks[hat_id]
    # Already patched?
    nxt = hat.get("next")
    if nxt and isinstance(blocks.get(nxt), dict):
        nb = blocks[nxt]
        if nb.get("opcode") == "looks_switchcostumeto":
            cin = nb.get("inputs", {}).get("COSTUME")
            if isinstance(cin, list) and len(cin) >= 2 and isinstance(cin[1], str):
                menu = blocks.get(cin[1])
                if isinstance(menu, dict) and (menu.get("fields") or {}).get("COSTUME", [None])[0] == "b3":
                    print(f"  {target['name']}: Phase 2 handler already has switch b3 — skip")
                    return
    old_next = hat.get("next")
    switch_id, _ = make_switch_to_b3(blocks, hat_id)
    stop_id = make_stop_other(blocks, switch_id)
    blocks[switch_id]["next"] = stop_id
    blocks[stop_id]["next"] = old_next
    hat["next"] = switch_id
    if old_next and old_next in blocks and isinstance(blocks[old_next], dict):
        blocks[old_next]["parent"] = stop_id
    print(f"  {target['name']}: Phase 2 → switch b3 → stop others → existing")


def png_asset(png_bytes: bytes) -> tuple[str, str, int, float, float]:
    md5 = hashlib.md5(png_bytes).hexdigest()
    md5ext = f"{md5}.png"
    im = Image.open(io.BytesIO(png_bytes))
    w, h = im.size
    # Scratch bitmap rotation centers are in pixels (match Durple/Simon)
    return md5, md5ext, 2, w / 2, h / 2


def set_costume_png(c: dict, md5: str, md5ext: str, cx: float, cy: float) -> None:
    c["assetId"] = md5
    c["md5ext"] = md5ext
    c["dataFormat"] = "png"
    c["bitmapResolution"] = 2
    c["rotationCenterX"] = cx
    c["rotationCenterY"] = cy


def ensure_b3(target: dict, template: dict) -> None:
    names = [c["name"] for c in target["costumes"]]
    if "b3" in names:
        print("  b3 already present")
        return
    # Insert after idle2 if present, else after idle
    idx = 2
    if "idle2" in names:
        idx = names.index("idle2") + 1
    elif "idle" in names:
        idx = names.index("idle") + 1
    new_c = dict(template)
    new_c["name"] = "b3"
    target["costumes"].insert(idx, new_c)
    print(f"  inserted b3 at index {idx}")


def assign_body(target: dict, phase1: bytes, phase2: bytes, assets: dict) -> None:
    m1, e1, _, cx1, cy1 = png_asset(phase1)
    m2, e2, _, cx2, cy2 = png_asset(phase2)
    assets[e1] = phase1
    assets[e2] = phase2

    ensure_b3(target, {
        "name": "b3",
        "bitmapResolution": 2,
        "dataFormat": "png",
        "assetId": m2,
        "md5ext": e2,
        "rotationCenterX": cx2,
        "rotationCenterY": cy2,
    })

    for c in target["costumes"]:
        name = c["name"]
        if name == "b3" or "???" in name:
            set_costume_png(c, m2, e2, cx2, cy2)
            print(f"  costume {name} → phase2 {e2} center=({cx2},{cy2})")
        else:
            # Phase 1: idle, idle2, anim*
            set_costume_png(c, m1, e1, cx1, cy1)
            print(f"  costume {name} → phase1 {e1} center=({cx1},{cy1})")


def assign_icons(data: dict, icon_pngs: dict[str, bytes], assets: dict) -> None:
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
    for c in icons["costumes"]:
        if c["name"] not in icon_pngs:
            continue
        blob = icon_pngs[c["name"]]
        md5, md5ext, _, cx, cy = png_asset(blob)
        assets[md5ext] = blob
        set_costume_png(c, md5, md5ext, cx, cy)
        print(f"  Icons {c['name']} → {md5ext} {Image.open(io.BytesIO(blob)).size}")


def main() -> None:
    print("1) Process Phase 1 + Phase 2 PNGs")
    p1 = knock_black_bg(Image.open(SRC_P1))
    p2 = knock_black_bg(Image.open(SRC_P2))
    ART_P1.parent.mkdir(parents=True, exist_ok=True)
    p1.save(ART_P1, "PNG")
    p2.save(ART_P2, "PNG")
    p1_bytes = ART_P1.read_bytes()
    p2_bytes = ART_P2.read_bytes()
    print(f"  {ART_P1.name} {p1.size} ({len(p1_bytes)} bytes)")
    print(f"  {ART_P2.name} {p2.size} ({len(p2_bytes)} bytes)")

    print("2) Face icons from Phase 1")
    icon_pngs = make_face_icons(p1)

    print("3) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    pinki = next(t for t in data["targets"] if t["name"] == SPRITE)
    print("4) Assign Pinki costumes + add b3")
    assign_body(pinki, p1_bytes, p2_bytes, assets)

    print("5) Assign Icons 18-a/b/c")
    assign_icons(data, icon_pngs, assets)

    print("6) Phase 2 instant-swap on Pinki")
    patch_phase2_handler(pinki)

    print("7) Write sb3 (prune unused)")
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

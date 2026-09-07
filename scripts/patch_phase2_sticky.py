#!/usr/bin/env python3
"""Add Oren Phase 2 art; sticky b3 forever + Switch Costume phase guards for custom chars."""
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
ART_OREN_P2 = ROOT / "art" / "oren-phase2.png"
SRC_OREN_P2 = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments/"
    "72a3ef00b74b70bc999258acf5dba08003758366ee2f642b611476a87defadc8.png"
)

TARGET_H = 400
PHASE_VAR = ["phase", "S,?j6u%g[aITivaNIVAy"]
FREEZE_VAR = ["Freeze Muted Polos?", "r@4Q#Z.#s4+ffZLv_SIK"]
ENABLED_LIST = ["Enabled List", "otV.lpFDROzle:X0p7@2"]
BROADCAST_PHASE2 = ["Phase 2", "2qOY4J,K81HY:t`XJFlx"]

SPRITES = {
    "Pink (Pinki)": {"polo": ";+wrg/Amc[W^sm.(mec/"},
    "Yellow (Simon)": {"polo": "ctjyyBb0ne6Quc}unU;U"},
    "Purple (Durple)": {"polo": "wQIw|I/wX06uu^MvOkoG"},
    "Orange (Oren)": {"polo": "jow+X5YboB.E3NYpTw[U"},
}


def uid(n: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "#%()*+,-./:;=?@[]^_{}~"
    return "".join(random.choice(alphabet) for _ in range(n))


def new_id(blocks: dict) -> str:
    for _ in range(120):
        i = uid()
        if i not in blocks:
            return i
    raise RuntimeError("id collision")


def knock_black_bg(im: Image.Image, thresh: int = 35) -> Image.Image:
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
    # also knock near-white near-transparent edge noise (alpha<=2)
    near_white = (rgb.min(axis=2) >= 250) & (a <= 2)
    out[near_white, 3] = 0
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
        "mutation": {"tagName": "mutation", "children": [], "hasnext": "true"},
    }
    return stmt


def make_wait0(blocks: dict, parent: str | None) -> str:
    stmt = new_id(blocks)
    shadow = new_id(blocks)
    blocks[shadow] = {
        "opcode": "math_number",
        "next": None,
        "parent": stmt,
        "inputs": {},
        "fields": {"NUM": ["0", None]},
        "shadow": True,
        "topLevel": False,
    }
    blocks[stmt] = {
        "opcode": "control_wait",
        "next": None,
        "parent": parent,
        "inputs": {"DURATION": [1, shadow]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    return stmt


def make_phase_eq_2(blocks: dict, parent: str) -> str:
    eq = new_id(blocks)
    blocks[eq] = {
        "opcode": "operator_equals",
        "next": None,
        "parent": parent,
        "inputs": {
            "OPERAND1": [3, [12, PHASE_VAR[0], PHASE_VAR[1]], [10, ""]],
            "OPERAND2": [1, [10, "2"]],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    return eq


def find_phase2_hat(blocks: dict) -> str:
    for bid, b in blocks.items():
        if not isinstance(b, dict):
            continue
        if b.get("opcode") != "event_whenbroadcastreceived":
            continue
        opt = (b.get("fields") or {}).get("BROADCAST_OPTION")
        if opt and opt[0] == "Phase 2":
            return bid
    raise RuntimeError("No Phase 2 hat")


def chain_ends_with_opcode(blocks: dict, start: str, opcode: str) -> bool:
    cur = start
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        b = blocks.get(cur)
        if not isinstance(b, dict):
            return False
        if b.get("opcode") == opcode and b.get("next") is None:
            # check nested forever as last after if
            pass
        if b.get("next") is None:
            return b.get("opcode") == opcode
        cur = b.get("next")
    return False


def ensure_phase2_prefix(target: dict) -> str:
    """Ensure Phase 2 starts with switch b3 → stop others. Return hat id."""
    blocks = target["blocks"]
    hat_id = find_phase2_hat(blocks)
    hat = blocks[hat_id]
    nxt = hat.get("next")
    already = False
    if nxt and isinstance(blocks.get(nxt), dict):
        nb = blocks[nxt]
        if nb.get("opcode") == "looks_switchcostumeto":
            cin = nb.get("inputs", {}).get("COSTUME")
            if isinstance(cin, list) and len(cin) >= 2 and isinstance(cin[1], str):
                menu = blocks.get(cin[1])
                if isinstance(menu, dict) and (menu.get("fields") or {}).get("COSTUME", [None])[0] == "b3":
                    stop = nb.get("next")
                    if stop and isinstance(blocks.get(stop), dict) and blocks[stop].get("opcode") == "control_stop":
                        already = True
    if already:
        print(f"  {target['name']}: Phase 2 prefix OK (b3+stop)")
        return hat_id
    old_next = hat.get("next")
    switch_id = make_switch_to_b3(blocks, hat_id)
    stop_id = make_stop_other(blocks, switch_id)
    blocks[switch_id]["next"] = stop_id
    blocks[stop_id]["next"] = old_next
    hat["next"] = switch_id
    if old_next and old_next in blocks and isinstance(blocks[old_next], dict):
        blocks[old_next]["parent"] = stop_id
    print(f"  {target['name']}: Phase 2 → switch b3 → stop others")
    return hat_id


def append_sticky_forever(target: dict, hat_id: str) -> None:
    """Append forever{ if phase==2: switch b3; wait 0 } at end of Phase 2 chain."""
    blocks = target["blocks"]
    # Detect existing sticky: forever with switch b3 after Phase 2 hat
    cur = hat_id
    seen = set()
    last = hat_id
    while cur and cur not in seen:
        seen.add(cur)
        b = blocks[cur]
        if not isinstance(b, dict):
            break
        if b.get("opcode") == "control_forever":
            # already has forever on this chain
            print(f"  {target['name']}: sticky forever already present — skip")
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
        "inputs": {
            "CONDITION": [2, eq_id],
            "SUBSTACK": [2, switch_id],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    blocks[switch_id]["parent"] = if_id
    blocks[switch_id]["next"] = None
    blocks[wait_id]["parent"] = forever_id
    blocks[wait_id]["next"] = None

    blocks[forever_id] = {
        "opcode": "control_forever",
        "next": None,
        "parent": last,
        "inputs": {"SUBSTACK": [2, if_id]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    blocks[last]["next"] = forever_id
    print(f"  {target['name']}: appended sticky forever b3 while phase==2")


def delete_block_tree(blocks: dict, root: str | None) -> None:
    if not root or root not in blocks:
        return
    to_visit = [root]
    seen = set()
    while to_visit:
        bid = to_visit.pop()
        if not bid or bid in seen or bid not in blocks:
            continue
        seen.add(bid)
        b = blocks[bid]
        if not isinstance(b, dict):
            continue
        if b.get("next"):
            to_visit.append(b["next"])
        for v in (b.get("inputs") or {}).values():
            if isinstance(v, list):
                for item in v[1:]:
                    if isinstance(item, str):
                        to_visit.append(item)
    for bid in seen:
        del blocks[bid]


def find_switch_costume_def(blocks: dict) -> tuple[str, str]:
    for bid, b in blocks.items():
        if not isinstance(b, dict):
            continue
        if b.get("opcode") != "procedures_definition":
            continue
        pin = b.get("inputs", {}).get("custom_block")
        if not (isinstance(pin, list) and len(pin) >= 2 and isinstance(pin[1], str)):
            continue
        proto = blocks.get(pin[1])
        if isinstance(proto, dict) and (proto.get("mutation") or {}).get("proccode") == "Switch Costume %s":
            return bid, pin[1]
    raise RuntimeError("Switch Costume %s not found")


def rebuild_switch_costume(target: dict, polo_id: str) -> None:
    """Replace Switch Costume body with Simon-style phase==2 → b3 guard."""
    blocks = target["blocks"]
    def_id, proto_id = find_switch_costume_def(blocks)
    old_next = blocks[def_id].get("next")
    delete_block_tree(blocks, old_next)

    polo_field = ["Polo Im On RN", polo_id]

    def nid() -> str:
        return new_id(blocks)

    # Build from leaves up
    # --- enabled branch ---
    # cos arg reporters
    def make_arg(parent: str) -> str:
        a = nid()
        blocks[a] = {
            "opcode": "argument_reporter_string_number",
            "next": None,
            "parent": parent,
            "inputs": {},
            "fields": {"VALUE": ["cos", None]},
            "shadow": False,
            "topLevel": False,
        }
        return a

    def make_costume_menu(parent: str, name: str) -> str:
        m = nid()
        blocks[m] = {
            "opcode": "looks_costume",
            "next": None,
            "parent": parent,
            "inputs": {},
            "fields": {"COSTUME": [name, None]},
            "shadow": True,
            "topLevel": False,
        }
        return m

    def make_switch_menu(parent: str, name: str) -> str:
        s = nid()
        menu = make_costume_menu(s, name)
        blocks[s] = {
            "opcode": "looks_switchcostumeto",
            "next": None,
            "parent": parent,
            "inputs": {"COSTUME": [1, menu]},
            "fields": {},
            "shadow": False,
            "topLevel": False,
        }
        return s

    def make_switch_arg(parent: str) -> str:
        s = nid()
        arg = make_arg(s)
        # shadow menu still present in Simon? He uses [3, arg, shadow] sometimes
        shadow = make_costume_menu(s, "idle")
        blocks[s] = {
            "opcode": "looks_switchcostumeto",
            "next": None,
            "parent": parent,
            "inputs": {"COSTUME": [3, arg, shadow]},
            "fields": {},
            "shadow": False,
            "topLevel": False,
        }
        return s

    # Inner: if (contains ??? OR cos==b3) then ARG else b3
    if_horror_ok = nid()
    switch_arg_horror = make_switch_arg(if_horror_ok)
    switch_b3_force = make_switch_menu(if_horror_ok, "b3")

    # or(contains(cos,"???"), cos=="b3")
    or_id = nid()
    contains_id = nid()
    eq_b3 = nid()
    arg_c1 = make_arg(contains_id)
    text_qqq = nid()
    blocks[text_qqq] = {
        "opcode": "text",
        "next": None,
        "parent": contains_id,
        "inputs": {},
        "fields": {"TEXT": ["???", None]},
        "shadow": True,
        "topLevel": False,
    }
    blocks[contains_id] = {
        "opcode": "operator_contains",
        "next": None,
        "parent": or_id,
        "inputs": {"STRING1": [2, arg_c1], "STRING2": [1, text_qqq]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    arg_c2 = make_arg(eq_b3)
    text_b3 = nid()
    blocks[text_b3] = {
        "opcode": "text",
        "next": None,
        "parent": eq_b3,
        "inputs": {},
        "fields": {"TEXT": ["b3", None]},
        "shadow": True,
        "topLevel": False,
    }
    blocks[eq_b3] = {
        "opcode": "operator_equals",
        "next": None,
        "parent": or_id,
        "inputs": {"OPERAND1": [2, arg_c2], "OPERAND2": [1, text_b3]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    blocks[or_id] = {
        "opcode": "operator_or",
        "next": None,
        "parent": if_horror_ok,
        "inputs": {"OPERAND1": [2, contains_id], "OPERAND2": [2, eq_b3]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    blocks[if_horror_ok] = {
        "opcode": "control_if_else",
        "next": None,
        "parent": None,  # filled
        "inputs": {
            "CONDITION": [2, or_id],
            "SUBSTACK": [2, switch_arg_horror],
            "SUBSTACK2": [2, switch_b3_force],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }

    # if phase==2 then horror_ok else switch ARG
    if_phase_en = nid()
    eq_phase_en = nid()
    text_2a = nid()
    blocks[text_2a] = {
        "opcode": "text",
        "next": None,
        "parent": eq_phase_en,
        "inputs": {},
        "fields": {"TEXT": ["2", None]},
        "shadow": True,
        "topLevel": False,
    }
    blocks[eq_phase_en] = {
        "opcode": "operator_equals",
        "next": None,
        "parent": if_phase_en,
        "inputs": {
            "OPERAND1": [3, [12, PHASE_VAR[0], PHASE_VAR[1]], [10, ""]],
            "OPERAND2": [1, text_2a],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    switch_arg_p1 = make_switch_arg(if_phase_en)
    blocks[if_horror_ok]["parent"] = if_phase_en
    blocks[if_phase_en] = {
        "opcode": "control_if_else",
        "next": None,
        "parent": None,
        "inputs": {
            "CONDITION": [2, eq_phase_en],
            "SUBSTACK": [2, if_horror_ok],
            "SUBSTACK2": [2, switch_arg_p1],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }

    # --- muted branch ---
    if_phase_mute = nid()
    eq_phase_mute = nid()
    blocks[eq_phase_mute] = {
        "opcode": "operator_equals",
        "next": None,
        "parent": if_phase_mute,
        "inputs": {
            "OPERAND1": [3, [12, PHASE_VAR[0], PHASE_VAR[1]], [10, ""]],
            "OPERAND2": [1, [10, "2"]],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    switch_b3_mute = make_switch_menu(if_phase_mute, "b3")
    switch_idle_mute = make_switch_menu(if_phase_mute, "idle")
    blocks[if_phase_mute] = {
        "opcode": "control_if_else",
        "next": None,
        "parent": None,
        "inputs": {
            "CONDITION": [2, eq_phase_mute],
            "SUBSTACK": [2, switch_b3_mute],
            "SUBSTACK2": [2, switch_idle_mute],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }

    if_freeze = nid()
    eq_freeze = nid()
    blocks[eq_freeze] = {
        "opcode": "operator_equals",
        "next": None,
        "parent": if_freeze,
        "inputs": {
            "OPERAND1": [3, [12, FREEZE_VAR[0], FREEZE_VAR[1]], [10, ""]],
            "OPERAND2": [1, [10, "1"]],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    blocks[if_phase_mute]["parent"] = if_freeze
    blocks[if_freeze] = {
        "opcode": "control_if",
        "next": None,
        "parent": None,
        "inputs": {
            "CONDITION": [2, eq_freeze],
            "SUBSTACK": [2, if_phase_mute],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }

    # top: if enabled
    top_if = nid()
    eq_en = nid()
    item = nid()
    blocks[item] = {
        "opcode": "data_itemoflist",
        "next": None,
        "parent": eq_en,
        "inputs": {
            "INDEX": [3, [12, polo_field[0], polo_field[1]], [7, "1"]],
        },
        "fields": {"LIST": ENABLED_LIST},
        "shadow": False,
        "topLevel": False,
    }
    blocks[eq_en] = {
        "opcode": "operator_equals",
        "next": None,
        "parent": top_if,
        "inputs": {
            "OPERAND1": [2, item],
            "OPERAND2": [1, [10, "1"]],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    blocks[if_phase_en]["parent"] = top_if
    blocks[if_freeze]["parent"] = top_if
    blocks[top_if] = {
        "opcode": "control_if_else",
        "next": None,
        "parent": def_id,
        "inputs": {
            "CONDITION": [2, eq_en],
            "SUBSTACK": [2, if_phase_en],
            "SUBSTACK2": [2, if_freeze],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    blocks[def_id]["next"] = top_if
    print(f"  {target['name']}: rebuilt Switch Costume %s with phase→b3 guards")


def ensure_oren_phase2(target: dict, p2_bytes: bytes, assets: dict) -> None:
    md5, md5ext, cx, cy = png_asset(p2_bytes)
    assets[md5ext] = p2_bytes
    names = [c["name"] for c in target["costumes"]]
    if "b3" not in names:
        # insert after idle2
        idx = names.index("idle2") + 1 if "idle2" in names else 2
        target["costumes"].insert(
            idx,
            {
                "name": "b3",
                "bitmapResolution": 2,
                "dataFormat": "png",
                "assetId": md5,
                "md5ext": md5ext,
                "rotationCenterX": cx,
                "rotationCenterY": cy,
            },
        )
        print(f"  inserted b3 at {idx}")
    for c in target["costumes"]:
        name = c["name"]
        if name == "b3" or "???" in name:
            set_costume_png(c, md5, md5ext, cx, cy)
            print(f"  costume {name} → phase2 {md5ext}")


def main() -> None:
    print("1) Process Oren Phase 2 PNG")
    p2 = knock_black_bg(Image.open(SRC_OREN_P2))
    ART_OREN_P2.parent.mkdir(parents=True, exist_ok=True)
    p2.save(ART_OREN_P2, "PNG")
    p2_bytes = ART_OREN_P2.read_bytes()
    print(f"  {ART_OREN_P2} {p2.size} ({len(p2_bytes)} bytes)")

    print("2) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    # Confirm Oren P1 still present
    oren = next(t for t in data["targets"] if t["name"] == "Orange (Oren)")
    idle = next(c for c in oren["costumes"] if c["name"] == "idle")
    print(f"  Oren Phase1 idle asset: {idle.get('md5ext')} (keep)")

    print("3) Assign Oren Phase 2 costumes")
    ensure_oren_phase2(oren, p2_bytes, assets)

    print("4) Phase 2 sticky + Switch Costume for all custom sprites")
    for name, meta in SPRITES.items():
        target = next(t for t in data["targets"] if t["name"] == name)
        print(f"\n-- {name} --")
        # Ensure b3 exists (Oren just got it; others should have it)
        if not any(c["name"] == "b3" for c in target["costumes"]):
            raise RuntimeError(f"{name} missing b3")
        hat = ensure_phase2_prefix(target)
        append_sticky_forever(target, hat)
        rebuild_switch_costume(target, meta["polo"])

    print("\n5) Write sb3")
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

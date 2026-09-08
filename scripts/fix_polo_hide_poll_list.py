#!/usr/bin/env python3
"""Fix gray Polo hide/show after Restart stops the Is active? forever.

Root causes (both symptoms share one mechanism):
1) fix_reset_clear (6d30497) added `stop other scripts` on Polo Restart so
   Restart Polo does not stack. That also kills the green-flag forever that
   copies Polos[n] → Is active?.
2) 0d41aaa made Is active? = (item n of Polos = 1). Restart Polo still waits
   on Is active?, which is frozen after the stop.
3) Saved project state has Polos = [0,0,0,1,0,0,0] and Polo 4 Is active?=1
   (center slot). Forever briefly sets Is active?=1 before Restart stops it
   → center ghosts immediately and never recovers. Other slots stay at
   Is active?=0 forever → never hide on drop.

Fix (no AABB hitbox restore):
- Restart Polo polls item(slot) of Polos directly for occupy/empty.
- Sync Is active? when entering/leaving ghost so eye-anim vars stay coherent.
- Reset saved Polos to seven 0s and every Polo Is active? to 0.
"""
from __future__ import annotations

import io
import json
import random
import string
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
POLOS_LIST = ["Polos", "If`q7--T^C)-E6Ngo]V^"]


def uid(n: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "#%()*+,-./:;=?@[]^_{}~"
    return "".join(random.choice(alphabet) for _ in range(n))


def new_id(blocks: dict) -> str:
    for _ in range(400):
        i = uid()
        if i not in blocks:
            return i
    raise RuntimeError("id collision")


def find_proc_def(blocks: dict, proccode: str) -> tuple[str, str] | None:
    for bid, b in blocks.items():
        if not isinstance(b, dict) or b.get("opcode") != "procedures_prototype":
            continue
        if (b.get("mutation") or {}).get("proccode") != proccode:
            continue
        for did, d in blocks.items():
            if (
                isinstance(d, dict)
                and d.get("opcode") == "procedures_definition"
                and (d.get("inputs") or {}).get("custom_block", [None, None])[1] == bid
            ):
                return did, bid
    return None


def is_active_var(target: dict) -> list | None:
    for vid, v in (target.get("variables") or {}).items():
        if isinstance(v, list) and v[0] == "Is active?":
            return [v[0], vid]
    return None


def make_polos_equals(blocks: dict, parent: str, slot: int, value: str) -> str:
    """Build operator_equals(item(slot of Polos), value); return eq block id."""
    item_id = new_id(blocks)
    eq_id = new_id(blocks)
    blocks[item_id] = {
        "opcode": "data_itemoflist",
        "next": None,
        "parent": eq_id,
        "inputs": {"INDEX": [1, [7, str(slot)]]},
        "fields": {"LIST": list(POLOS_LIST)},
        "shadow": False,
        "topLevel": False,
    }
    blocks[eq_id] = {
        "opcode": "operator_equals",
        "next": None,
        "parent": parent,
        "inputs": {
            "OPERAND1": [3, item_id, [10, ""]],
            "OPERAND2": [1, [10, value]],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    return eq_id


def make_set_is_active(blocks: dict, parent: str, polo_var: list, value: str) -> str:
    bid = new_id(blocks)
    blocks[bid] = {
        "opcode": "data_setvariableto",
        "next": None,
        "parent": parent,
        "inputs": {"VALUE": [1, [10, value]]},
        "fields": {"VARIABLE": list(polo_var)},
        "shadow": False,
        "topLevel": False,
    }
    return bid


def patch_restart_polo(target: dict, slot: int) -> str:
    blocks = target["blocks"]
    found = find_proc_def(blocks, "Restart Polo")
    if not found:
        return "no Restart Polo"
    def_id, _ = found
    polo_var = is_active_var(target)
    if not polo_var:
        return "no Is active?"

    # Walk Restart Polo body: find repeat_until (occupy) and wait_until (empty)
    # after the ghost=100 seteffect.
    repeat_id = None
    wait_id = None
    ghost100_id = None
    show_id = None
    cur = blocks[def_id].get("next")
    while cur and cur in blocks:
        b = blocks[cur]
        if not isinstance(b, dict):
            break
        op = b.get("opcode")
        if op == "looks_show":
            show_id = cur
        if op == "control_repeat_until" and repeat_id is None:
            repeat_id = cur
        if op == "looks_seteffectto":
            # VALUE 100 = hide via ghost
            val = (b.get("inputs") or {}).get("VALUE", [None, None])
            lit = val[1] if isinstance(val[1], list) else None
            if lit and len(lit) >= 2 and str(lit[1]) == "100":
                ghost100_id = cur
        if op == "control_wait_until" and ghost100_id and wait_id is None:
            wait_id = cur
        cur = b.get("next")

    if not repeat_id or not wait_id:
        return f"missing loops repeat={repeat_id} wait={wait_id}"

    # Replace conditions with Polos[slot] checks (delete old inline var reporters —
    # they are not separate blocks, only field tuples, so nothing to delete).
    eq1 = make_polos_equals(blocks, repeat_id, slot, "1")
    blocks[repeat_id]["inputs"]["CONDITION"] = [2, eq1]

    eq0 = make_polos_equals(blocks, wait_id, slot, "0")
    blocks[wait_id]["inputs"]["CONDITION"] = [2, eq0]

    # After show: force Is active?=0 (clear stale center save).
    if show_id:
        rest = blocks[show_id].get("next")
        set0 = make_set_is_active(blocks, show_id, polo_var, "0")
        blocks[set0]["next"] = rest
        blocks[show_id]["next"] = set0
        if rest and rest in blocks and isinstance(blocks[rest], dict):
            blocks[rest]["parent"] = set0

    # Before ghost 100: set Is active?=1
    if ghost100_id:
        parent = blocks[ghost100_id].get("parent")
        # insert set1 between parent and ghost100
        set1 = make_set_is_active(blocks, parent or def_id, polo_var, "1")
        blocks[set1]["next"] = ghost100_id
        blocks[ghost100_id]["parent"] = set1
        if parent and parent in blocks:
            # parent.next may be repeat_until; ghost follows repeat. Find who points to ghost100
            for bid, b in blocks.items():
                if isinstance(b, dict) and b.get("next") == ghost100_id and bid != set1:
                    b["next"] = set1
                    blocks[set1]["parent"] = bid
                    break

    # After wait_until empty: set Is active?=0 before the following wait
    rest = blocks[wait_id].get("next")
    set0b = make_set_is_active(blocks, wait_id, polo_var, "0")
    blocks[set0b]["next"] = rest
    blocks[wait_id]["next"] = set0b
    if rest and rest in blocks and isinstance(blocks[rest], dict):
        blocks[rest]["parent"] = set0b

    # Persist variable default
    for vid, v in target["variables"].items():
        if isinstance(v, list) and v[0] == "Is active?":
            v[1] = 0

    return f"Restart Polo polls Polos[{slot}]"


def main() -> None:
    print("Load", SB3)
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    stage = data["targets"][0]
    for lid, lv in (stage.get("lists") or {}).items():
        if lv[0] == "Polos":
            old = list(lv[1])
            lv[1] = ["0"] * 7
            print(f"  Stage Polos {old} → {lv[1]}")
        if lv[0] == "Characters":
            # clear any leftover occupied character flags from saved play
            if any(str(x) != "0" for x in lv[1]):
                print(f"  Stage Characters had nonzeros: {lv[1]} → all 0")
                lv[1] = ["0"] * len(lv[1])
        if lv[0] == "Enabled List":
            if lv[1] != ["1"] * 7:
                print(f"  Stage Enabled List {lv[1]} → all 1")
                lv[1] = ["1"] * 7

    # Clear demo polo/character globals left from a saved session
    for vid, vv in (stage.get("variables") or {}).items():
        if vv[0] == "Polo number" and str(vv[1]) not in ("0", "0.0", ""):
            print(f"  clear Polo number {vv[1]} → 0")
            vv[1] = 0
        if vv[0] == "Character" and str(vv[1]) not in ("0", "0.0", ""):
            print(f"  clear Character {vv[1]} → 0")
            vv[1] = 0

    for t in data["targets"]:
        name = t["name"]
        if not name.startswith("Polo "):
            continue
        slot = int(name.split()[1])
        print(f"  {name}: {patch_restart_polo(t, slot)}")

    # Verify each Restart Polo condition uses itemoflist Polos
    for t in data["targets"]:
        if not t["name"].startswith("Polo "):
            continue
        slot = int(t["name"].split()[1])
        blocks = t["blocks"]
        found = find_proc_def(blocks, "Restart Polo")
        cur = blocks[found[0]].get("next")
        saw_item = 0
        while cur and cur in blocks:
            b = blocks[cur]
            if isinstance(b, dict) and b.get("opcode") in (
                "control_repeat_until",
                "control_wait_until",
            ):
                cond = (b.get("inputs") or {}).get("CONDITION", [None, None])[1]
                if cond and blocks.get(cond, {}).get("opcode") == "operator_equals":
                    op1 = (blocks[cond].get("inputs") or {}).get("OPERAND1", [None, None])[1]
                    if (
                        isinstance(op1, str)
                        and blocks.get(op1, {}).get("opcode") == "data_itemoflist"
                        and (blocks[op1].get("fields") or {}).get("LIST", [None])[0] == "Polos"
                    ):
                        idx = (blocks[op1].get("inputs") or {}).get("INDEX", [None, [None, None]])
                        lit = idx[1][1] if isinstance(idx[1], list) else None
                        if str(lit) == str(slot):
                            saw_item += 1
            cur = b.get("next") if isinstance(b, dict) else None
        if saw_item < 2:
            raise SystemExit(f"{t['name']}: expected 2 Polos polls, got {saw_item}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(data, separators=(",", ":")))
        for name, blob in sorted(assets.items()):
            z.writestr(name, blob)
    SB3.write_bytes(buf.getvalue())
    print(f"wrote {SB3} ({SB3.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

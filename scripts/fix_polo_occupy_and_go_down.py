#!/usr/bin/env python3
"""Fix Polo hide-when-occupied + restore broken go down from 6d30497.

Root causes:
1) Polo Is active? used touching(character) after AABB hitbox SVGs were
   stripped (a41e84e). Occupancy never flipped → gray polos stayed visible.
2) fix_reset_clear.strip_go_down_timer_wait used delete_tree() which follows
   `next`, so it deleted the entire rest of go down after the timer if.
   All 20 characters left with a dangling next to a missing block.

Fix:
- Restore go down bodies from pre-6d30497 sb3; strip timer wait without
  following next; keep Restart→stop→go down; clear Polos[slot] + Polo Im On RN.
- Icons Start Polo marks Polos[n]=1 immediately on drop.
- Polo Is active? forever checks item (n) of Polos == 1 (no touching).
"""
from __future__ import annotations

import copy
import io
import json
import random
import string
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
POLOS_LIST = ["Polos", "If`q7--T^C)-E6Ngo]V^"]
POLO_NUM_VAR = ["Polo number", "whUqM~$[{O)4o(|Ju8^9"]

CHAR_NAMES = {
    "Orange (Oren)",
    "Red (Raddy)",
    "Silver (Clukr)",
    "Fun Bot",
    "Green (Vineria)",
    "Gray (Gray)",
    "Brown (brud)",
    "Gold (Garnold)",
    "Lime (OWAKCX)",
    "Sky blue (Sky)",
    "Mr. Sun",
    "Purple (Durple)",
    "Mr. Tree",
    "Yellow (Simon)",
    "Tan (Tunner)",
    "Mr. Fun Computer",
    "White (Wenda)",
    "Pink (Pinki)",
    "Blue (Jevin)",
    "Black?",
}


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


def collect_input_tree(blocks: dict, root: str | None) -> set[str]:
    """Block ids reachable via inputs/substacks only (NOT sibling next chain)."""
    if not root or root not in blocks:
        return set()
    out: set[str] = set()
    stack = [root]
    while stack:
        bid = stack.pop()
        if not bid or bid in out or bid not in blocks:
            continue
        out.add(bid)
        b = blocks[bid]
        if not isinstance(b, dict):
            continue
        for v in (b.get("inputs") or {}).values():
            if isinstance(v, list):
                for item in v[1:]:
                    if isinstance(item, str):
                        stack.append(item)
    return out


def collect_chain_and_inputs(blocks: dict, root: str | None) -> set[str]:
    """Follow next + inputs from root."""
    if not root or root not in blocks:
        return set()
    out: set[str] = set()
    stack = [root]
    while stack:
        bid = stack.pop()
        if not bid or bid in out or bid not in blocks:
            continue
        out.add(bid)
        b = blocks[bid]
        if not isinstance(b, dict):
            continue
        if b.get("next"):
            stack.append(b["next"])
        for v in (b.get("inputs") or {}).values():
            if isinstance(v, list):
                for item in v[1:]:
                    if isinstance(item, str):
                        stack.append(item)
    return out


def delete_input_tree(blocks: dict, root: str | None) -> None:
    for bid in collect_input_tree(blocks, root):
        blocks.pop(bid, None)


def strip_go_down_timer_wait(blocks: dict, def_id: str) -> str:
    """Unlink timer-wait control_if; delete only that if's input tree (not next)."""
    body = blocks[def_id].get("next")
    cur = body
    prev = def_id
    while cur and cur in blocks:
        b = blocks[cur]
        if not isinstance(b, dict):
            break
        if b.get("opcode") == "control_if":
            sub = (b.get("inputs") or {}).get("SUBSTACK", [None, None])[1]
            if sub and isinstance(blocks.get(sub), dict) and blocks[sub].get("opcode") == "control_wait_until":
                nxt = b.get("next")
                if prev == def_id:
                    blocks[def_id]["next"] = nxt
                else:
                    blocks[prev]["next"] = nxt
                if nxt and nxt in blocks and isinstance(blocks[nxt], dict):
                    blocks[nxt]["parent"] = prev
                # Do NOT follow next — only this if + its inputs
                delete_input_tree(blocks, cur)
                blocks.pop(cur, None)
                return "stripped timer wait"
        prev = cur
        cur = b.get("next")
    return "wait already absent"


def make_stop_other(blocks: dict, parent: str) -> str:
    bid = new_id(blocks)
    blocks[bid] = {
        "opcode": "control_stop",
        "next": None,
        "parent": parent,
        "inputs": {},
        "fields": {"STOP_OPTION": ["other scripts in sprite", None]},
        "shadow": False,
        "topLevel": False,
    }
    return bid


def make_call_go_down(blocks: dict, parent: str) -> str:
    bid = new_id(blocks)
    blocks[bid] = {
        "opcode": "procedures_call",
        "next": None,
        "parent": parent,
        "inputs": {},
        "fields": {},
        "shadow": False,
        "topLevel": False,
        "mutation": {
            "tagName": "mutation",
            "children": [],
            "proccode": "go down",
            "argumentids": "[]",
            "warp": "false",
        },
    }
    return bid


def fix_restart_hat(target: dict) -> str:
    blocks = target["blocks"]
    if not find_proc_def(blocks, "go down"):
        return "no go down"
    for hat_id, hat in list(blocks.items()):
        if not isinstance(hat, dict):
            continue
        if hat.get("opcode") != "event_whenbroadcastreceived":
            continue
        if "Restart" not in str(hat.get("fields")):
            continue
        old_next = hat.get("next")
        # Delete previous Restart chain fully (hat's next chain)
        for bid in collect_chain_and_inputs(blocks, old_next):
            blocks.pop(bid, None)
        stop_id = make_stop_other(blocks, hat_id)
        call_id = make_call_go_down(blocks, stop_id)
        blocks[stop_id]["next"] = call_id
        hat["next"] = stop_id
        return "rewired Restart→stop→go down"
    return "no Restart hat"


def fix_polo_restart(target: dict) -> str:
    blocks = target["blocks"]
    for hat_id, hat in list(blocks.items()):
        if not isinstance(hat, dict):
            continue
        if hat.get("opcode") != "event_whenbroadcastreceived":
            continue
        if "Restart" not in str(hat.get("fields")):
            continue
        nxt = hat.get("next")
        if nxt and isinstance(blocks.get(nxt), dict) and blocks[nxt].get("opcode") == "control_stop":
            return "already stops"
        stop_id = make_stop_other(blocks, hat_id)
        blocks[stop_id]["next"] = nxt
        if nxt and nxt in blocks and isinstance(blocks[nxt], dict):
            blocks[nxt]["parent"] = stop_id
        hat["next"] = stop_id
        return "added stop before Restart Polo"
    return "no Restart"


def polo_im_on_var(target: dict) -> list | None:
    for vid, v in (target.get("variables") or {}).items():
        if isinstance(v, list) and v[0] == "Polo Im On RN":
            return [v[0], vid]
    return None


def inject_go_down_slot_clear(target: dict) -> str:
    """At start of go down (after optional function call): clear Polos[slot] + Polo Im On RN."""
    blocks = target["blocks"]
    found = find_proc_def(blocks, "go down")
    if not found:
        return "no go down"
    def_id, _ = found
    polo_var = polo_im_on_var(target)
    if not polo_var:
        return "no Polo Im On RN"

    body = blocks[def_id].get("next")
    # Insert after leading procedures_call function if present
    insert_after = def_id
    if body and isinstance(blocks.get(body), dict) and blocks[body].get("opcode") == "procedures_call":
        insert_after = body

    rest = blocks[insert_after].get("next")

    # replace item (Polo Im On RN) of Polos with 0
    rep_id = new_id(blocks)
    # set Polo Im On RN to 0
    set_id = new_id(blocks)

    blocks[rep_id] = {
        "opcode": "data_replaceitemoflist",
        "next": set_id,
        "parent": insert_after,
        "inputs": {
            "INDEX": [3, [12, polo_var[0], polo_var[1]], [7, "1"]],
            "ITEM": [1, [10, "0"]],
        },
        "fields": {"LIST": list(POLOS_LIST)},
        "shadow": False,
        "topLevel": False,
    }
    blocks[set_id] = {
        "opcode": "data_setvariableto",
        "next": rest,
        "parent": rep_id,
        "inputs": {"VALUE": [1, [10, "0"]]},
        "fields": {"VARIABLE": list(polo_var)},
        "shadow": False,
        "topLevel": False,
    }
    blocks[insert_after]["next"] = rep_id
    if rest and rest in blocks and isinstance(blocks[rest], dict):
        blocks[rest]["parent"] = set_id
    return "clears Polos[slot]+Polo Im On RN"


def restore_go_down_from_old(curr: dict, old: dict) -> str:
    """Replace current go down body with a copy of old's go down body."""
    c_blocks = curr["blocks"]
    o_blocks = old["blocks"]
    c_found = find_proc_def(c_blocks, "go down")
    o_found = find_proc_def(o_blocks, "go down")
    if not c_found or not o_found:
        return "missing go down"
    c_def, _ = c_found
    o_def, _ = o_found

    # Remove current body (may be dangling)
    old_body = c_blocks[c_def].get("next")
    for bid in collect_chain_and_inputs(c_blocks, old_body):
        c_blocks.pop(bid, None)

    o_body = o_blocks[o_def].get("next")
    ids = collect_chain_and_inputs(o_blocks, o_body)
    # Remap ids that collide with existing non-copied blocks
    id_map: dict[str, str] = {}
    for bid in ids:
        if bid in c_blocks:
            id_map[bid] = new_id(c_blocks)
        else:
            id_map[bid] = bid

    def remap_val(v):
        if isinstance(v, str) and v in id_map:
            return id_map[v]
        if isinstance(v, list):
            return [remap_val(x) for x in v]
        if isinstance(v, dict):
            return {k: remap_val(x) for k, x in v.items()}
        return v

    for bid in ids:
        nb = copy.deepcopy(o_blocks[bid])
        nb = remap_val(nb)
        if isinstance(nb, dict) and nb.get("parent") == o_def:
            nb["parent"] = c_def
        c_blocks[id_map[bid]] = nb

    c_blocks[c_def]["next"] = id_map.get(o_body, o_body) if o_body else None
    return f"restored {len(ids)} blocks"


def patch_icons_start_polo(icons: dict) -> str:
    blocks = icons["blocks"]
    found = find_proc_def(blocks, "Start Polo %s with Character %s")
    if not found:
        return "no Start Polo"
    def_id, proto_id = found
    # After setting Polo number + Character, mark Polos[n]=1 before Enabled List / broadcast
    # Find data_setvariableto Character then insert after it
    cur = blocks[def_id].get("next")
    character_set = None
    while cur and cur in blocks:
        b = blocks[cur]
        if (
            isinstance(b, dict)
            and b.get("opcode") == "data_setvariableto"
            and (b.get("fields") or {}).get("VARIABLE", [""])[0] == "Character"
        ):
            character_set = cur
            break
        cur = b.get("next") if isinstance(b, dict) else None
    if not character_set:
        return "no Character set"

    # Avoid double-insert
    nxt = blocks[character_set].get("next")
    if nxt and isinstance(blocks.get(nxt), dict):
        nb = blocks[nxt]
        if nb.get("opcode") == "data_replaceitemoflist" and (nb.get("fields") or {}).get("LIST", [""])[0] == "Polos":
            return "already marks Polos"

    # Need arg reporter for Polo number — reuse shadow from Polo number set if possible
    # INDEX: Polo number variable (stage) which was just set
    rep_id = new_id(blocks)
    rest = blocks[character_set].get("next")
    blocks[rep_id] = {
        "opcode": "data_replaceitemoflist",
        "next": rest,
        "parent": character_set,
        "inputs": {
            "INDEX": [3, [12, POLO_NUM_VAR[0], POLO_NUM_VAR[1]], [7, "1"]],
            "ITEM": [1, [10, "1"]],
        },
        "fields": {"LIST": list(POLOS_LIST)},
        "shadow": False,
        "topLevel": False,
    }
    blocks[character_set]["next"] = rep_id
    if rest and rest in blocks and isinstance(blocks[rest], dict):
        blocks[rest]["parent"] = rep_id
    return "Start Polo marks Polos[n]=1"


def simplify_polo_active(target: dict, slot: int) -> str:
    """Replace touching OR with item(slot) of Polos == 1."""
    blocks = target["blocks"]
    # Find flag hat that hides then forever if_else setting Is active?
    for hat_id, hat in blocks.items():
        if not isinstance(hat, dict) or hat.get("opcode") != "event_whenflagclicked":
            continue
        # walk to forever
        cur = hat.get("next")
        forever_id = None
        while cur and cur in blocks:
            b = blocks[cur]
            if not isinstance(b, dict):
                break
            if b.get("opcode") == "control_forever":
                forever_id = cur
                break
            cur = b.get("next")
        if not forever_id:
            continue
        forever = blocks[forever_id]
        sub = (forever.get("inputs") or {}).get("SUBSTACK", [None, None])[1]
        if not sub or not isinstance(blocks.get(sub), dict):
            continue
        iff = blocks[sub]
        if iff.get("opcode") != "control_if_else":
            continue
        # Confirm it sets Is active?
        then_id = (iff.get("inputs") or {}).get("SUBSTACK", [None, None])[1]
        if not then_id or not isinstance(blocks.get(then_id), dict):
            continue
        then_b = blocks[then_id]
        if then_b.get("opcode") != "data_setvariableto":
            continue
        if (then_b.get("fields") or {}).get("VARIABLE", [""])[0] != "Is active?":
            continue

        # Delete old CONDITION input tree only
        old_cond = (iff.get("inputs") or {}).get("CONDITION", [None, None])[1]
        delete_input_tree(blocks, old_cond)

        # Build: equals(item(slot, Polos), 1)
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
            "parent": sub,
            "inputs": {
                "OPERAND1": [3, item_id, [10, ""]],
                "OPERAND2": [1, [10, "1"]],
            },
            "fields": {},
            "shadow": False,
            "topLevel": False,
        }
        iff["inputs"]["CONDITION"] = [2, eq_id]

        # Remove obsolete replaceitemoflist on Polos from then/else chains
        # (Characters/Icons now own occupancy.) Keep Is active sets.
        for branch in ("SUBSTACK", "SUBSTACK2"):
            start = (iff.get("inputs") or {}).get(branch, [None, None])[1]
            cur = start
            prev = None
            while cur and cur in blocks:
                b = blocks[cur]
                if not isinstance(b, dict):
                    break
                nxt = b.get("next")
                if (
                    b.get("opcode") == "data_replaceitemoflist"
                    and (b.get("fields") or {}).get("LIST", [""])[0] == "Polos"
                ):
                    # unlink
                    if prev is None:
                        # first in branch — shouldn't happen (Is active is first)
                        iff["inputs"][branch] = [2, nxt] if nxt else [2, None]
                        if nxt and nxt in blocks:
                            blocks[nxt]["parent"] = sub
                    else:
                        blocks[prev]["next"] = nxt
                        if nxt and nxt in blocks:
                            blocks[nxt]["parent"] = prev
                    blocks.pop(cur, None)
                    cur = nxt
                    continue
                prev = cur
                cur = nxt

        return f"Is active? ← Polos[{slot}]"
    return "no Is active forever"


def load_old_project() -> dict:
    raw = subprocess.check_output(["git", "show", "6d30497^:sprunki-base.sb3"], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        return json.loads(z.read("project.json"))


def main() -> None:
    print("Load", SB3)
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    old = load_old_project()
    old_by_name = {t["name"]: t for t in old["targets"]}

    for t in data["targets"]:
        name = t["name"]
        if name in CHAR_NAMES:
            o = old_by_name[name]
            print(f"  {name}: {restore_go_down_from_old(t, o)}")
            print(f"    {strip_go_down_timer_wait(t['blocks'], find_proc_def(t['blocks'], 'go down')[0])}")
            print(f"    {inject_go_down_slot_clear(t)}")
            print(f"    {fix_restart_hat(t)}")
        elif name.startswith("Polo "):
            slot = int(name.split()[1])
            print(f"  {name}: {simplify_polo_active(t, slot)}; {fix_polo_restart(t)}")
        elif name == "Icons":
            print(f"  Icons: {patch_icons_start_polo(t)}")

    # Verify go down intact
    bad = []
    for t in data["targets"]:
        if t["name"] not in CHAR_NAMES:
            continue
        blocks = t["blocks"]
        found = find_proc_def(blocks, "go down")
        cur = blocks[found[0]].get("next")
        steps = 0
        while cur and steps < 80:
            if cur not in blocks:
                bad.append(t["name"])
                break
            cur = blocks[cur].get("next") if isinstance(blocks[cur], dict) else None
            steps += 1
        else:
            if steps < 5:
                bad.append(f"{t['name']}(short:{steps})")
    if bad:
        raise SystemExit(f"go down still broken: {bad}")
    print("go down OK for all characters")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(data, separators=(",", ":")))
        for name, blob in sorted(assets.items()):
            z.writestr(name, blob)
    SB3.write_bytes(buf.getvalue())
    print(f"wrote {SB3} ({SB3.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

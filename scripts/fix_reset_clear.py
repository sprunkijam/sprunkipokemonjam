#!/usr/bin/env python3
"""Fix Reset so every on-stage Sprunki clears in Phase 1 and Phase 2.

Root cause:
  1) Character Restart only called `go down` when touching Bars — a thin
     top/bottom UI strip. Smaller costumes (Clukr/Fun Bot/Garnold) and
     fringe-cropped art often miss Bars, so they never clear.
  2) `go down` waits until timer < 1 when near the loop end. Restart also
     clears the Characters list → Putted characters → 0 → loop controller
     stops resetting the timer. Characters stuck in that wait never hide
     (Phase 1 and Phase 2). Phase 2 sticky forever then keeps b3 costumes
     on still-visible sprites.

Fix:
  - Restart → stop other scripts, then go down (no Bars gate).
  - Strip the timer wait from every character's `go down` so reset cannot hang.
  - Polo Restart → stop other scripts before Restart Polo (avoid stacked loops).
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
    for _ in range(200):
        i = uid()
        if i not in blocks:
            return i
    raise RuntimeError("id collision")


def delete_tree(blocks: dict, root: str | None, *, follow_next: bool = True) -> None:
    """Delete a block subtree. follow_next=True also walks sibling `next` links
    (hat bodies). Use follow_next=False when unlinking a single middle block
    whose `next` must survive (e.g. stripping the go-down timer wait)."""
    if not root or root not in blocks:
        return
    stack = [root]
    seen: set[str] = set()
    while stack:
        bid = stack.pop()
        if not bid or bid in seen or bid not in blocks:
            continue
        seen.add(bid)
        b = blocks[bid]
        if not isinstance(b, dict):
            continue
        if follow_next and b.get("next"):
            stack.append(b["next"])
        for v in (b.get("inputs") or {}).values():
            if isinstance(v, list):
                for item in v[1:]:
                    if isinstance(item, str):
                        stack.append(item)
    for bid in seen:
        del blocks[bid]


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


def make_call_go_down(blocks: dict, parent: str, proto_id: str, proccode: str = "go down") -> str:
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
            "proccode": proccode,
            "argumentids": "[]",
            "warp": "false",
        },
    }
    return bid


def fix_restart_hat(target: dict) -> str:
    """Restart → stop other scripts → go down (no Bars gate)."""
    blocks = target["blocks"]
    found = find_proc_def(blocks, "go down")
    if not found:
        return "no go down"
    def_id, proto_id = found

    for hat_id, hat in list(blocks.items()):
        if not isinstance(hat, dict):
            continue
        if hat.get("opcode") != "event_whenbroadcastreceived":
            continue
        if "Restart" not in str(hat.get("fields")):
            continue

        old_next = hat.get("next")
        # Delete previous chain under Restart (Bars if + call)
        delete_tree(blocks, old_next)

        stop_id = make_stop_other(blocks, hat_id)
        call_id = make_call_go_down(blocks, stop_id, proto_id)
        blocks[stop_id]["next"] = call_id
        hat["next"] = stop_id
        return "rewired Restart→stop→go down"
    return "no Restart hat"


def strip_go_down_timer_wait(target: dict) -> str:
    blocks = target["blocks"]
    found = find_proc_def(blocks, "go down")
    if not found:
        return "no go down"
    def_id, _ = found
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
                # unlink this if; keep its next
                nxt = b.get("next")
                if prev == def_id:
                    blocks[def_id]["next"] = nxt
                else:
                    blocks[prev]["next"] = nxt
                if nxt and nxt in blocks and isinstance(blocks[nxt], dict):
                    blocks[nxt]["parent"] = prev
                delete_tree(blocks, cur, follow_next=False)
                return "stripped timer wait"
        prev = cur
        cur = b.get("next")
    return "wait already absent"


def fix_polo_restart(target: dict) -> str:
    blocks = target["blocks"]
    for hat_id, hat in list(blocks.items()):
        if not isinstance(hat, dict):
            continue
        if hat.get("opcode") != "event_whenbroadcastreceived":
            continue
        if "Restart" not in str(hat.get("fields")):
            continue
        # If already starts with stop, skip
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


def main() -> None:
    print("Load", SB3)
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    for t in data["targets"]:
        name = t["name"]
        if name in CHAR_NAMES:
            a = fix_restart_hat(t)
            b = strip_go_down_timer_wait(t)
            print(f"  {name}: {a}; {b}")
        elif name.startswith("Polo "):
            print(f"  {name}: {fix_polo_restart(t)}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(data, separators=(",", ":")))
        for name, blob in sorted(assets.items()):
            z.writestr(name, blob)
    SB3.write_bytes(buf.getvalue())
    print(f"wrote {SB3} ({SB3.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

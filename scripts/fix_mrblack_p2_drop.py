#!/usr/bin/env python3
"""Fix Black? Start Polo drop: always switched to idle (P1).

When phase already == 2, Black stayed on idle. When he triggers Phase 2 himself,
Phase 2 hat switches to b3 — but if dropped while phase is already 2, nothing
forced b3. Rewrite the unconditional idle switch to phase==2 → b3 else idle,
and force b3 right after his Phase 2 broadcast.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_phase2_sticky import (  # noqa: E402
    PHASE_VAR,
    append_sticky_forever,
    ensure_phase2_prefix,
    make_phase_eq_2,
    make_switch_to_b3,
    new_id,
)

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
SPRITE = "Black?"

# Known Start Polo drop chain ids (Character == 20)
IDLE_SWITCH = "d{"  # looks_switchcostumeto idle
IDLE_MENU = "KD"
PARENT_BEFORE = "p}"  # motion_changeyby → was d{
NEXT_AFTER = "p~"  # looks_gotofrontback
PHASE1_IF = ":6B!F^HGt*ao?=kruACM"
PHASE1_TRUE_START = "A[$|q~~NfH(g{w[$nz6M"
PHASE2_BCAST = "4|iJ*fH,~^xtZ}%X03%o"


def costume_of(blocks: dict, sid: str) -> str | None:
    b = blocks.get(sid)
    if not b or b.get("opcode") != "looks_switchcostumeto":
        return None
    cin = b.get("inputs", {}).get("COSTUME")
    if not isinstance(cin, list) or len(cin) < 2:
        return None
    val = cin[1]
    if isinstance(val, str) and val in blocks:
        menu = blocks[val]
        if menu.get("opcode") == "looks_costume":
            return (menu.get("fields") or {}).get("COSTUME", [None])[0]
    return None


def fix_drop_phase_costume(target: dict) -> None:
    blocks = target["blocks"]
    if IDLE_SWITCH not in blocks:
        raise RuntimeError(f"missing idle switch {IDLE_SWITCH}")
    old = blocks[IDLE_SWITCH]
    if old.get("opcode") != "looks_switchcostumeto":
        raise RuntimeError(f"{IDLE_SWITCH} is not switchcostume: {old.get('opcode')}")
    if costume_of(blocks, IDLE_SWITCH) not in ("idle", "idle2", "b3"):
        print(f"  WARN: {IDLE_SWITCH} costume was {costume_of(blocks, IDLE_SWITCH)}")

    # Build: if phase==2: switch b3 else: switch idle
    if_id = new_id(blocks)
    eq_id = make_phase_eq_2(blocks, if_id)
    sw_b3 = make_switch_to_b3(blocks, if_id)
    sw_idle = new_id(blocks)
    menu_idle = new_id(blocks)
    blocks[menu_idle] = {
        "opcode": "looks_costume",
        "next": None,
        "parent": sw_idle,
        "inputs": {},
        "fields": {"COSTUME": ["idle", None]},
        "shadow": True,
        "topLevel": False,
    }
    blocks[sw_idle] = {
        "opcode": "looks_switchcostumeto",
        "next": None,
        "parent": if_id,
        "inputs": {"COSTUME": [1, menu_idle]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    blocks[if_id] = {
        "opcode": "control_if_else",
        "next": NEXT_AFTER,
        "parent": PARENT_BEFORE,
        "inputs": {
            "CONDITION": [2, eq_id],
            "SUBSTACK": [2, sw_b3],
            "SUBSTACK2": [2, sw_idle],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }

    # Relink chain: p} → if_id → p~
    blocks[PARENT_BEFORE]["next"] = if_id
    if NEXT_AFTER in blocks:
        blocks[NEXT_AFTER]["parent"] = if_id

    # Delete old idle switch + its menu if orphaned
    old_menu = None
    cin = old.get("inputs", {}).get("COSTUME")
    if isinstance(cin, list) and len(cin) >= 2 and isinstance(cin[1], str):
        old_menu = cin[1]
    del blocks[IDLE_SWITCH]
    if old_menu and old_menu in blocks and blocks[old_menu].get("opcode") == "looks_costume":
        del blocks[old_menu]
    print(f"  replaced {IDLE_SWITCH} idle with phase==2 → b3 / else idle ({if_id})")


def force_b3_after_phase2_broadcast(target: dict) -> None:
    """After Black broadcasts Phase 2, also switch to b3 immediately."""
    blocks = target["blocks"]
    if PHASE2_BCAST not in blocks:
        print("  WARN: Phase 2 broadcast block missing — skip force b3")
        return
    bcast = blocks[PHASE2_BCAST]
    if bcast.get("opcode") != "event_broadcast":
        raise RuntimeError(f"{PHASE2_BCAST} not broadcast")
    # Already forced?
    nxt = bcast.get("next")
    if nxt and nxt in blocks and blocks[nxt].get("opcode") == "looks_switchcostumeto":
        if costume_of(blocks, nxt) == "b3":
            print("  force b3 after broadcast already present")
            return
    old_next = bcast.get("next")
    sw = make_switch_to_b3(blocks, PHASE2_BCAST)
    blocks[sw]["next"] = old_next
    bcast["next"] = sw
    if old_next and old_next in blocks:
        blocks[old_next]["parent"] = sw
    print(f"  inserted switch b3 after Phase 2 broadcast → {sw}")


def verify(target: dict) -> None:
    blocks = target["blocks"]
    # Walk Start Polo Character chain for phase==2 costume
    found_p2 = False
    found_idle_else = False
    # Find the if we inserted: parent p}, next p~
    for bid, b in blocks.items():
        if not isinstance(b, dict):
            continue
        if b.get("opcode") != "control_if_else":
            continue
        if b.get("parent") != PARENT_BEFORE or b.get("next") != NEXT_AFTER:
            continue
        sub = (b.get("inputs") or {}).get("SUBSTACK", [None, None])[1]
        sub2 = (b.get("inputs") or {}).get("SUBSTACK2", [None, None])[1]
        c1 = costume_of(blocks, sub) if isinstance(sub, str) else None
        c2 = costume_of(blocks, sub2) if isinstance(sub2, str) else None
        print(f"  verify drop if {bid}: true={c1} else={c2}")
        if c1 == "b3":
            found_p2 = True
        if c2 == "idle":
            found_idle_else = True
    if not found_p2 or not found_idle_else:
        raise SystemExit("VERIFY FAIL: Start Polo drop not phase==2→b3 / idle")
    # sticky Phase 2
    hats = [
        bid
        for bid, b in blocks.items()
        if isinstance(b, dict)
        and b.get("opcode") == "event_whenbroadcastreceived"
        and (b.get("fields") or {}).get("BROADCAST_OPTION", [None])[0] == "Phase 2"
    ]
    print(f"  Phase 2 hats: {hats}")
    assert hats, "no Phase 2 hat"
    # costumes
    names = [c["name"] for c in target["costumes"]]
    assert "b3" in names
    assert any("???" in n for n in names)
    print(f"  costumes ok: {[n for n in names if n in ('idle','b3') or '???' in n or n.startswith('anim')]}")


def main() -> None:
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    black = next(t for t in data["targets"] if t["name"] == SPRITE)
    print("1) Fix Start Polo drop costume (phase==2 → b3)")
    fix_drop_phase_costume(black)
    print("2) Force b3 after Black's Phase 2 broadcast")
    force_b3_after_phase2_broadcast(black)
    print("3) Ensure Phase 2 sticky still present")
    hat = ensure_phase2_prefix(black)
    append_sticky_forever(black, hat)
    print("4) Verify")
    verify(black)

    buf = SB3.with_suffix(".sb3.tmp")
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(data, separators=(",", ":")))
        for name, blob in assets.items():
            z.writestr(name, blob)
    buf.replace(SB3)
    print(f"wrote {SB3} ({SB3.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

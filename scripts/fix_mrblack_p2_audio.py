#!/usr/bin/env python3
"""Fix Black? first-drop silent Phase 2.

Root cause: Start Polo Phase-2-entry broadcasts Phase 2; Phase 2 hat does
control_stop other scripts in sprite, which kills:
  - the Start Polo forever that keeps volume at 100
  - the Start Polo drop script itself (often during wait 2), so Characters[20]
    never becomes 1 → Loop 1/2 never call play loop.

Second drop works because Phase 2 does not re-fire and Characters gets set.

Fix:
  1) Phase 2 hat: after stop (before sticky forever) — Characters[20]=1,
     MuteEnable=1, if Enabled List[Polo] != 0 then volume 100 + play loop 1,
     else volume 0.
  2) Start Polo Phase-2-entry: set Characters[20]=1 before broadcast; after
     switch-b3, set volume 100 (respect mute) + play loop before wait.
Costume sticky / drop→b3 unchanged.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_phase2_sticky import new_id  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
SPRITE = "Black?"

MUTE_VAR = ["MuteEnable", "nB)AW_-*E{9{N7gSr{x6"]
CHARS_LIST = ["Characters", "j9R~|FP%-)0.b_ZqX1+*"]
ENABLED_LIST = ["Enabled List", "otV.lpFDROzle:X0p7@2"]
POLO_VAR = ["Polo Im On RN", "iY@x:9-akvVBr3xjgzNR"]

PHASE2_HAT = "vKcpgwh6v,jb7;GC)lo}"
PHASE2_STOP = "{F;*5Lq/;8#+.:7=%^)?"
PHASE2_STICKY = "1YN[0hJXl%^F(U{L*,/["

# Start Polo phase-2-entry
SET_PHASE2 = "A[$|q~~NfH(g{w[$nz6M"
PHASE2_BCAST = "4|iJ*fH,~^xtZ}%X03%o"
SWITCH_B3_AFTER = "rkk/7C[1}Lmkj[(:,yaZ"
WAIT2 = "L6)}6~aZpfIs|;d_88^m"
CHARS_AFTER_WAIT = "KG"

PLAY_LOOP_ARG = "PlU`%L_.)XI|:QSp_!:#"


def make_set_mute_enable(blocks: dict, parent: str | None, value: str = "1") -> str:
    bid = new_id(blocks)
    blocks[bid] = {
        "opcode": "data_setvariableto",
        "next": None,
        "parent": parent,
        "inputs": {"VALUE": [1, [10, value]]},
        "fields": {"VARIABLE": [MUTE_VAR[0], MUTE_VAR[1]]},
        "shadow": False,
        "topLevel": False,
    }
    return bid


def make_chars20(blocks: dict, parent: str | None, item: str = "1") -> str:
    bid = new_id(blocks)
    blocks[bid] = {
        "opcode": "data_replaceitemoflist",
        "next": None,
        "parent": parent,
        "inputs": {
            "INDEX": [1, [7, "20"]],
            "ITEM": [1, [10, item]],
        },
        "fields": {"LIST": [CHARS_LIST[0], CHARS_LIST[1]]},
        "shadow": False,
        "topLevel": False,
    }
    return bid


def make_volume(blocks: dict, parent: str | None, vol: str) -> str:
    bid = new_id(blocks)
    blocks[bid] = {
        "opcode": "sound_setvolumeto",
        "next": None,
        "parent": parent,
        "inputs": {"VOLUME": [1, [4, vol]]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    return bid


def make_play_loop(blocks: dict, parent: str | None, loop: str = "1") -> str:
    bid = new_id(blocks)
    blocks[bid] = {
        "opcode": "procedures_call",
        "next": None,
        "parent": parent,
        "inputs": {PLAY_LOOP_ARG: [1, [10, loop]]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
        "mutation": {
            "tagName": "mutation",
            "children": [],
            "proccode": "play loop %s",
            "argumentids": json.dumps([PLAY_LOOP_ARG]),
            "warp": "false",
        },
    }
    return bid


def make_enabled_eq_0(blocks: dict, parent: str) -> str:
    """operator_equals: item of Enabled List (Polo Im On RN) == 0"""
    item = new_id(blocks)
    eq = new_id(blocks)
    blocks[item] = {
        "opcode": "data_itemoflist",
        "next": None,
        "parent": eq,
        "inputs": {
            "INDEX": [3, [12, POLO_VAR[0], POLO_VAR[1]], [7, "1"]],
        },
        "fields": {"LIST": [ENABLED_LIST[0], ENABLED_LIST[1]]},
        "shadow": False,
        "topLevel": False,
    }
    blocks[eq] = {
        "opcode": "operator_equals",
        "next": None,
        "parent": parent,
        "inputs": {
            "OPERAND1": [3, item, [10, ""]],
            "OPERAND2": [1, [10, "0"]],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    return eq


def make_mute_aware_audio(blocks: dict, parent: str | None) -> tuple[str, str]:
    """Build: if Enabled==0: volume 0 else: volume 100 → play loop 1.
    Returns (first_id, last_id).
    """
    if_id = new_id(blocks)
    eq = make_enabled_eq_0(blocks, if_id)
    vol0 = make_volume(blocks, if_id, "0")
    vol100 = make_volume(blocks, if_id, "100")
    play = make_play_loop(blocks, vol100, "1")
    blocks[vol100]["next"] = play
    blocks[play]["parent"] = vol100
    blocks[if_id] = {
        "opcode": "control_if_else",
        "next": None,
        "parent": parent,
        "inputs": {
            "CONDITION": [2, eq],
            "SUBSTACK": [2, vol0],
            "SUBSTACK2": [2, vol100],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    return if_id, if_id


def link(blocks: dict, a: str, b: str | None) -> None:
    blocks[a]["next"] = b
    if b and b in blocks:
        blocks[b]["parent"] = a


def already_fixed_phase2(blocks: dict) -> bool:
    """Detect our MuteEnable set inserted after stop."""
    stop = blocks.get(PHASE2_STOP)
    if not stop:
        return False
    nxt = stop.get("next")
    if not nxt or nxt not in blocks:
        return False
    b = blocks[nxt]
    if b.get("opcode") != "data_setvariableto":
        return False
    return (b.get("fields") or {}).get("VARIABLE", [None])[0] == "MuteEnable"


def fix_phase2_hat(target: dict) -> None:
    blocks = target["blocks"]
    if PHASE2_STOP not in blocks or PHASE2_STICKY not in blocks:
        raise RuntimeError("Phase 2 stop/sticky missing")
    if already_fixed_phase2(blocks):
        print("  Phase 2 audio restart already present — skip")
        return

    # stop → mute1 → chars20=1 → mute-aware audio → sticky
    mute = make_set_mute_enable(blocks, PHASE2_STOP, "1")
    chars = make_chars20(blocks, mute, "1")
    audio, _ = make_mute_aware_audio(blocks, chars)
    sticky = PHASE2_STICKY

    link(blocks, PHASE2_STOP, mute)
    link(blocks, mute, chars)
    link(blocks, chars, audio)
    link(blocks, audio, sticky)
    print(f"  Phase 2 after stop: MuteEnable=1, Characters[20]=1, vol/play → sticky")


def fix_start_polo_phase2_entry(target: dict) -> None:
    blocks = target["blocks"]
    if SET_PHASE2 not in blocks or PHASE2_BCAST not in blocks:
        raise RuntimeError("Start Polo phase2 entry missing")

    # If Characters already inserted between set-phase and broadcast, skip dup
    nxt = blocks[SET_PHASE2].get("next")
    if nxt and nxt in blocks:
        b = blocks[nxt]
        if (
            b.get("opcode") == "data_replaceitemoflist"
            and (b.get("fields") or {}).get("LIST", [None])[0] == "Characters"
        ):
            print("  Start Polo early Characters[20]=1 already present")
        else:
            # set phase=2 → Characters[20]=1 → broadcast Phase 2
            chars = make_chars20(blocks, SET_PHASE2, "1")
            link(blocks, SET_PHASE2, chars)
            link(blocks, chars, PHASE2_BCAST)
            print("  inserted Characters[20]=1 before Phase 2 broadcast")
    else:
        chars = make_chars20(blocks, SET_PHASE2, "1")
        link(blocks, SET_PHASE2, chars)
        link(blocks, chars, PHASE2_BCAST)
        print("  inserted Characters[20]=1 before Phase 2 broadcast")

    # After switch b3 (following broadcast), before wait2: mute-aware audio
    if SWITCH_B3_AFTER not in blocks or WAIT2 not in blocks:
        raise RuntimeError("switch-b3 / wait2 missing after broadcast")
    sw = blocks[SWITCH_B3_AFTER]
    if sw.get("next") == WAIT2 or (
        sw.get("next")
        and sw.get("next") in blocks
        and blocks[sw["next"]].get("opcode") == "control_wait"
    ):
        # insert audio between switch and wait
        audio, _ = make_mute_aware_audio(blocks, SWITCH_B3_AFTER)
        old_next = sw.get("next")
        link(blocks, SWITCH_B3_AFTER, audio)
        link(blocks, audio, old_next)
        print("  after switch b3: volume/play (mute-aware) before wait")
    elif sw.get("next") and blocks.get(sw["next"], {}).get("opcode") == "control_if_else":
        print("  Start Polo post-b3 audio already present — skip")
    else:
        # try to find if already fixed
        cur = sw.get("next")
        found = False
        for _ in range(6):
            if not cur or cur not in blocks:
                break
            if blocks[cur].get("opcode") == "control_if_else":
                found = True
                break
            cur = blocks[cur].get("next")
        if found:
            print("  Start Polo post-b3 audio already present — skip")
        else:
            audio, _ = make_mute_aware_audio(blocks, SWITCH_B3_AFTER)
            old_next = sw.get("next")
            link(blocks, SWITCH_B3_AFTER, audio)
            link(blocks, audio, old_next)
            print("  after switch b3: volume/play (mute-aware) before wait")


def verify(target: dict) -> None:
    blocks = target["blocks"]
    # Phase 2 chain includes MuteEnable after stop
    assert already_fixed_phase2(blocks), "Phase 2 audio restart missing"
    # sticky still after audio
    stop = blocks[PHASE2_STOP]
    cur = stop.get("next")
    seen = []
    while cur and cur in blocks and len(seen) < 12:
        seen.append((cur, blocks[cur].get("opcode")))
        if cur == PHASE2_STICKY:
            break
        cur = blocks[cur].get("next")
    assert any(c == PHASE2_STICKY for c, _ in seen), f"sticky lost: {seen}"
    assert any(op == "procedures_call" for _, op in seen) or any(
        op == "control_if_else" for _, op in seen
    ), seen
    # b3 costume still on Phase 2 hat
    hat_next = blocks[PHASE2_HAT].get("next")
    assert blocks[hat_next].get("opcode") == "looks_switchcostumeto"
    print(f"  verify Phase 2 chain: {[op for _, op in seen]}")
    # Characters before broadcast
    nxt = blocks[SET_PHASE2].get("next")
    assert blocks[nxt].get("opcode") == "data_replaceitemoflist"
    print("  verify Characters before broadcast OK")


def main() -> None:
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    black = next(t for t in data["targets"] if t["name"] == SPRITE)
    print("1) Phase 2 hat: restart audio after stop")
    fix_phase2_hat(black)
    print("2) Start Polo Phase-2-entry: Characters early + audio")
    fix_start_polo_phase2_entry(black)
    print("3) Verify")
    verify(black)

    # Ensure sticky costume forever still intact
    sticky = black["blocks"][PHASE2_STICKY]
    assert sticky.get("opcode") == "control_forever"
    sub = (sticky.get("inputs") or {}).get("SUBSTACK", [None, None])[1]
    assert sub and black["blocks"][sub].get("opcode") == "control_if"
    print("  sticky forever intact")

    buf = SB3.with_suffix(".sb3.tmp")
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(data, separators=(",", ":")))
        for name, blob in assets.items():
            z.writestr(name, blob)
    buf.replace(SB3)
    print(f"wrote {SB3} ({SB3.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

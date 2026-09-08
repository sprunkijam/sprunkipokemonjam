#!/usr/bin/env python3
"""Fix Phase 2 drop: Start Polo / seated forever used idle2 when phase==2.

For every character sprite that has costume ``b3``, rewrite any
``looks_switchcostumeto idle2`` that sits in the true branch of
``if phase == 2`` to switch to ``b3`` instead.

Keeps Phase 2 broadcast sticky + Switch Costume guards untouched.
Skips sprites without ``b3`` (e.g. Lime / OWAKCX).
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
PHASE_NAME = "phase"


def costume_name(blocks: dict, switch_id: str) -> str | None:
    b = blocks.get(switch_id)
    if not b or b.get("opcode") != "looks_switchcostumeto":
        return None
    cin = b.get("inputs", {}).get("COSTUME")
    if not isinstance(cin, list) or len(cin) < 2:
        return None
    val = cin[1]
    if isinstance(val, list) and len(val) >= 2:
        return str(val[1])
    if isinstance(val, str) and val in blocks:
        menu = blocks[val]
        if menu.get("opcode") == "looks_costume":
            return (menu.get("fields") or {}).get("COSTUME", [None])[0]
    return None


def set_costume_menu(blocks: dict, switch_id: str, name: str) -> bool:
    b = blocks[switch_id]
    cin = b.get("inputs", {}).get("COSTUME")
    if not isinstance(cin, list) or len(cin) < 2:
        return False
    val = cin[1]
    if isinstance(val, str) and val in blocks:
        menu = blocks[val]
        if menu.get("opcode") == "looks_costume":
            menu.setdefault("fields", {})["COSTUME"] = [name, None]
            return True
    if isinstance(val, list) and len(val) >= 2:
        # rare literal form
        cin[1] = [val[0], name] + val[2:]
        return True
    return False


def is_phase_eq_2(blocks: dict, cond_id) -> bool:
    if not isinstance(cond_id, str) or cond_id not in blocks:
        return False
    cb = blocks[cond_id]
    if cb.get("opcode") != "operator_equals":
        return False

    def operand(inp) -> str:
        if not isinstance(inp, list) or len(inp) < 2:
            return ""
        v = inp[1]
        if isinstance(v, list) and len(v) >= 2:
            # [10,"2"] or [12,"phase",id]
            if v[0] == 12:
                return str(v[1])
            return str(v[1])
        if isinstance(v, str) and v in blocks:
            bb = blocks[v]
            if bb.get("opcode") == "data_variable":
                return (bb.get("fields") or {}).get("VARIABLE", [None])[0] or ""
            if bb.get("opcode") == "text":
                return (bb.get("fields") or {}).get("TEXT", [None])[0] or ""
        return ""

    o1 = operand(cb.get("inputs", {}).get("OPERAND1"))
    o2 = operand(cb.get("inputs", {}).get("OPERAND2"))
    return (o1 == PHASE_NAME and o2 == "2") or (o2 == PHASE_NAME and o1 == "2")


def walk_substack_switches(blocks: dict, start) -> list[str]:
    out: list[str] = []
    if not isinstance(start, str):
        return out
    seen: set[str] = set()
    cur: str | None = start
    while cur and cur not in seen:
        seen.add(cur)
        b = blocks.get(cur)
        if not b:
            break
        if b.get("opcode") == "looks_switchcostumeto":
            out.append(cur)
        # do not dive into nested ifs here — those have their own phase checks
        cur = b.get("next")
    return out


def fix_target(target: dict) -> list[str]:
    names = [c["name"] for c in target.get("costumes", [])]
    if "b3" not in names:
        return []
    blocks = target.get("blocks") or {}
    if not isinstance(blocks, dict):
        return []
    changes: list[str] = []
    for bid, b in list(blocks.items()):
        if not isinstance(b, dict):
            continue
        if b.get("opcode") not in ("control_if_else", "control_if"):
            continue
        cond = (b.get("inputs") or {}).get("CONDITION", [None, None])[1]
        if not is_phase_eq_2(blocks, cond):
            continue
        # True branch only (phase==2 → was idle2)
        sub = (b.get("inputs") or {}).get("SUBSTACK", [None, None])[1]
        for sid in walk_substack_switches(blocks, sub):
            if costume_name(blocks, sid) == "idle2":
                if set_costume_menu(blocks, sid, "b3"):
                    changes.append(sid)
    return changes


def verify_sample(proj: dict) -> None:
    """Sanity-check Gray / Oren / Wenda drop + forever phase==2 → b3."""
    for name in ("Gray (Gray)", "Orange (Oren)", "White (Wenda)"):
        t = next(x for x in proj["targets"] if x["name"] == name)
        blocks = t["blocks"]
        found = []
        for bid, b in blocks.items():
            if not isinstance(b, dict):
                continue
            if b.get("opcode") not in ("control_if_else", "control_if"):
                continue
            cond = (b.get("inputs") or {}).get("CONDITION", [None, None])[1]
            if not is_phase_eq_2(blocks, cond):
                continue
            sub = (b.get("inputs") or {}).get("SUBSTACK", [None, None])[1]
            for sid in walk_substack_switches(blocks, sub):
                found.append(costume_name(blocks, sid))
        bad = [c for c in found if c == "idle2"]
        print(f"  verify {name}: phase==2 costumes={found} bad_idle2={bad}")
        if bad:
            raise SystemExit(f"verify failed for {name}: still idle2 on phase==2")
        if "b3" not in found:
            raise SystemExit(f"verify failed for {name}: no b3 on phase==2 branch")


def main() -> None:
    with zipfile.ZipFile(SB3, "r") as z:
        proj = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    total = 0
    skipped = []
    for t in proj["targets"]:
        if t.get("isStage"):
            continue
        names = [c["name"] for c in t.get("costumes", [])]
        if "b3" not in names:
            if any(n in ("idle", "idle2") for n in names) and t["name"] not in (
                "Assets",
                "Icons",
                "Preview",
            ):
                skipped.append(t["name"])
            continue
        ch = fix_target(t)
        if ch:
            print(f"  {t['name']}: idle2→b3 x{len(ch)}")
            total += len(ch)
        else:
            # already fixed (e.g. Simon / Durple) or no phase==2 idle2
            print(f"  {t['name']}: no idle2-on-phase2 (ok)")

    if skipped:
        print(f"  skipped (no b3): {', '.join(skipped)}")

    print(f"\nTotal switches fixed: {total}")
    print("Verify Gray/Oren/Wenda:")
    verify_sample(proj)

    buf_path = SB3.with_suffix(".sb3.tmp")
    with zipfile.ZipFile(buf_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(proj, ensure_ascii=False, separators=(",", ":")))
        for name, data in assets.items():
            z.writestr(name, data)
    buf_path.replace(SB3)
    print(f"Wrote {SB3} ({SB3.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

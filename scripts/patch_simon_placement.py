#!/usr/bin/env python3
"""Tune Yellow (Simon) placed size, rotation centers, and layering."""
from __future__ import annotations

import io
import json
import random
import string
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
SPRITE = "Yellow (Simon)"

SIMON_SIZE = 82
P1_CX, P1_CY = 92.5, 144.0
P2_CX, P2_CY = 116.0, 168.0
LAYER_ADD = 1


def uid(n: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "#%()*+,-./:;=?@[]^_{}~"
    return "".join(random.choice(alphabet) for _ in range(n))


def new_id(blocks: dict) -> str:
    for _ in range(80):
        i = uid()
        if i not in blocks:
            return i
    raise RuntimeError("id collision")


def main() -> None:
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    simon = next(t for t in data["targets"] if t["name"] == SPRITE)
    blocks = simon["blocks"]

    print(f"1) size {simon.get("size")} -> {SIMON_SIZE}")
    simon["size"] = float(SIMON_SIZE)

    print("2) rotation centers")
    for c in simon["costumes"]:
        name = c["name"]
        if name in ("idle", "idle2") or (
            name.startswith("anim") and "???" not in name
        ):
            old = (c.get("rotationCenterX"), c.get("rotationCenterY"))
            c["rotationCenterX"] = P1_CX
            c["rotationCenterY"] = P1_CY
            print(f"  {name}: {old} -> ({P1_CX}, {P1_CY})")
        elif name == "b3" or "???" in name:
            old = (c.get("rotationCenterX"), c.get("rotationCenterY"))
            c["rotationCenterX"] = P2_CX
            c["rotationCenterY"] = P2_CY
            print(f"  {name}: {old} -> ({P2_CX}, {P2_CY})")

    print(f"3) layering forward add -> {LAYER_ADD}")
    ia = blocks.get("Ia")
    if not ia or ia.get("opcode") != "operator_add":
        raise RuntimeError(f"expected Ia operator_add, got {ia}")
    ia["inputs"]["NUM2"] = [1, [4, str(LAYER_ADD)]]
    dm = blocks.get("dm")
    if dm and dm.get("opcode") == "looks_goforwardbackwardlayers":
        num = dm["inputs"]["NUM"]
        if len(num) >= 3 and isinstance(num[2], list):
            dm["inputs"]["NUM"] = [num[0], num[1], [7, str(LAYER_ADD)]]
        print(f"  dm NUM now {dm["inputs"]["NUM"]}")

    print("4) looks_setsizeto before show")
    show = blocks.get("o2")
    if not show or show.get("opcode") != "looks_show":
        raise RuntimeError(f"expected o2 looks_show, got {show}")
    already = None
    for bid, b in blocks.items():
        if isinstance(b, dict) and b.get("opcode") == "looks_setsizeto":
            already = bid
            b["inputs"]["SIZE"] = [1, [4, str(SIMON_SIZE)]]
            print(f"  updated existing {bid}")
            break
    if already is None:
        if dm.get("next") != "o2":
            # maybe already inserted mid-chain
            mid = dm.get("next")
            mb = blocks.get(mid) if mid else None
            if mb and mb.get("opcode") == "looks_setsizeto":
                mb["inputs"]["SIZE"] = [1, [4, str(SIMON_SIZE)]]
                print("  size block already in chain")
            else:
                raise RuntimeError(f"dm.next expected o2, got {dm.get("next")}")
        else:
            sid = new_id(blocks)
            blocks[sid] = {
                "opcode": "looks_setsizeto",
                "next": "o2",
                "parent": "dm",
                "inputs": {"SIZE": [1, [4, str(SIMON_SIZE)]]},
                "fields": {},
                "shadow": False,
                "topLevel": False,
            }
            dm["next"] = sid
            show["parent"] = sid
            print(f"  inserted {sid}")

    print("5) write sb3")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(data, separators=(",", ":")))
        for name, blob in sorted(assets.items()):
            z.writestr(name, blob)
    SB3.write_bytes(buf.getvalue())
    print(f"  wrote {SB3} ({SB3.stat().st_size} bytes)")
    print("DONE")


if __name__ == "__main__":
    main()

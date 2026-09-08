#!/usr/bin/env python3
"""Lower Fun Bot (Magnemite) dropped size to match Oren/Tunner visual scale.

Wide art canvas (~810x400) made size-55 read huge; area-match vs Oren ≈ 41.
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
SPRITE = "Fun Bot"
# Area-match Oren solid silhouette; user range 35–42
FUNBOT_SIZE = 40


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

    fb = next(t for t in data["targets"] if t["name"] == SPRITE)
    blocks = fb["blocks"]
    before = fb.get("size")
    print(f"1) size {before} -> {FUNBOT_SIZE}")
    fb["size"] = float(FUNBOT_SIZE)

    # Start Polo drop chain: looks_goforwardbackwardlayers (b) -> looks_show (mB)
    layer = blocks.get("b)")
    show = blocks.get("mB")
    if not layer or layer.get("opcode") != "looks_goforwardbackwardlayers":
        raise RuntimeError(f"expected b) goforwardbackwardlayers, got {layer}")
    if not show or show.get("opcode") != "looks_show":
        raise RuntimeError(f"expected mB looks_show, got {show}")

    print("2) looks_setsizeto on Start Polo drop (before show)")
    existing = [
        bid
        for bid, b in blocks.items()
        if isinstance(b, dict) and b.get("opcode") == "looks_setsizeto"
    ]
    if existing:
        for bid in existing:
            blocks[bid]["inputs"]["SIZE"] = [1, [4, str(FUNBOT_SIZE)]]
            print(f"  updated existing {bid}")
    elif layer.get("next") == "mB":
        sid = new_id(blocks)
        blocks[sid] = {
            "opcode": "looks_setsizeto",
            "next": "mB",
            "parent": "b)",
            "inputs": {"SIZE": [1, [4, str(FUNBOT_SIZE)]]},
            "fields": {},
            "shadow": False,
            "topLevel": False,
        }
        layer["next"] = sid
        show["parent"] = sid
        print(f"  inserted {sid} between b) and mB")
    else:
        mid = layer.get("next")
        mb = blocks.get(mid) if mid else None
        if mb and mb.get("opcode") == "looks_setsizeto":
            mb["inputs"]["SIZE"] = [1, [4, str(FUNBOT_SIZE)]]
            print(f"  size block already in chain ({mid})")
        else:
            raise RuntimeError(f"b).next expected mB or setsizeto, got {mid}")

    # Also update any other looks_setsizeto that might appear later
    for bid, b in blocks.items():
        if isinstance(b, dict) and b.get("opcode") == "looks_setsizeto":
            b["inputs"]["SIZE"] = [1, [4, str(FUNBOT_SIZE)]]

    print("3) write sb3")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(data, separators=(",", ":")))
        for name, blob in sorted(assets.items()):
            z.writestr(name, blob)
    SB3.write_bytes(buf.getvalue())
    print(f"  wrote {SB3} ({SB3.stat().st_size} bytes)")

    with zipfile.ZipFile(SB3, "r") as z:
        data2 = json.loads(z.read("project.json"))
    fb2 = next(t for t in data2["targets"] if t["name"] == SPRITE)
    print("VERIFY size", fb2.get("size"))
    sizes = [
        (bid, b["inputs"]["SIZE"])
        for bid, b in fb2["blocks"].items()
        if isinstance(b, dict) and b.get("opcode") == "looks_setsizeto"
    ]
    print("VERIFY looks_setsizeto", sizes)
    # other chars unchanged
    for name in ("Orange (Oren)", "Tan (Tunner)", "Yellow (Simon)"):
        t = next(x for x in data2["targets"] if x["name"] == name)
        print(f"VERIFY {name} size still {t.get('size')}")
    print("DONE")


if __name__ == "__main__":
    main()

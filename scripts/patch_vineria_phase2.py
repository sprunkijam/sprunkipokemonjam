#!/usr/bin/env python3
"""Add Green (Vineria) Phase 2 art to b3 + anim???*; keep Phase 1; sticky already present."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from PIL import Image
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_phase2_sticky import (  # noqa: E402
    append_sticky_forever,
    ensure_phase2_prefix,
    knock_black_bg,
    png_asset,
    rebuild_switch_costume,
    set_costume_png,
)

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
ART_P2 = ROOT / "art" / "vineria-phase2.png"
SRC_P2 = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments/"
    "237c3c583a3b0f9f531cb374f752ca4008c19d28d1066fe09d4ec1098f10af77.png"
)
SPRITE = "Green (Vineria)"
POLO_ID = "ur?}lr(ey-KrLsfs,`X#"
PHASE1_MD5 = "57394347b05920c6fe51876fba77cfde.png"


def assign_phase2(target: dict, p2_bytes: bytes, assets: dict) -> None:
    md5, md5ext, cx, cy = png_asset(p2_bytes)
    assets[md5ext] = p2_bytes
    for c in target["costumes"]:
        name = c["name"]
        if name == "b3" or "???" in name:
            set_costume_png(c, md5, md5ext, cx, cy)
            print(f"  costume {name} -> phase2 {md5ext} cx={cx} cy={cy}")
        else:
            print(f"  costume {name} keep {c.get('md5ext')}")


def main() -> None:
    print("1) Process Vineria Phase 2 PNG")
    p2 = knock_black_bg(Image.open(SRC_P2))
    ART_P2.parent.mkdir(parents=True, exist_ok=True)
    p2.save(ART_P2, "PNG")
    p2_bytes = ART_P2.read_bytes()
    print(f"  {ART_P2.name} {p2.size} ({len(p2_bytes)} bytes)")

    print("2) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    simon = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    simon_size = simon.get("size")
    simon_cx = simon["costumes"][0].get("rotationCenterX")

    v = next(t for t in data["targets"] if t["name"] == SPRITE)
    idle = next(c for c in v["costumes"] if c["name"] == "idle")
    if idle.get("md5ext") != PHASE1_MD5:
        print(f"  WARN Phase1 idle is {idle.get('md5ext')} (expected {PHASE1_MD5})")
    else:
        print(f"  Phase1 idle OK {PHASE1_MD5}")

    print("3) Assign Phase 2 to b3 + anim???*")
    assign_phase2(v, p2_bytes, assets)

    print("4) Ensure sticky Phase 2 scripts")
    hat = ensure_phase2_prefix(v)
    append_sticky_forever(v, hat)
    # Switch Costume already rebuilt; re-run is safe/idempotent enough
    rebuild_switch_costume(v, POLO_ID)

    simon2 = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    assert simon2.get("size") == simon_size
    assert simon2["costumes"][0].get("rotationCenterX") == simon_cx
    print(f"  Simon still size={simon_size} cx={simon_cx} OK")

    # Phase1 still on non-??? costumes
    for c in v["costumes"]:
        if c["name"] in ("idle", "idle2") or (
            c["name"].startswith("anim") and "???" not in c["name"]
        ):
            assert c.get("md5ext") == PHASE1_MD5, c
    print("  Phase1 costumes still on phase1 art OK")

    print("5) Write sb3")
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

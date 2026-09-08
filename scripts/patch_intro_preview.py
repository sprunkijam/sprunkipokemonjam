#!/usr/bin/env python3
"""Replace Preview3/Preview4 (and optionally Preview2) with high-res intro bitmap.

Simon left · Gray center (larger/forward) · Pinki right on dark-blue navy radial bg.
Source master: art/intro-preview-gray-simon-pinki.png (1280×960, br=2 → 640×480).
Does NOT touch gameplay character sprites.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
ART = ROOT / "art" / "intro-preview-gray-simon-pinki.png"
SPRITE = "Preview"
# Same art for Preview3 + Preview4; also replace Preview2 for a clean set
REPLACE = ("Preview2", "Preview3", "Preview4")


def png_asset(blob: bytes) -> tuple[str, str, float, float, int, int]:
    md5 = hashlib.md5(blob).hexdigest()
    md5ext = f"{md5}.png"
    im = Image.open(io.BytesIO(blob))
    w, h = im.size
    return md5, md5ext, w / 2, h / 2, w, h


def set_costume_png(
    c: dict, md5: str, md5ext: str, cx: float, cy: float
) -> None:
    c["assetId"] = md5
    c["md5ext"] = md5ext
    c["dataFormat"] = "png"
    c["bitmapResolution"] = 2
    c["rotationCenterX"] = cx
    c["rotationCenterY"] = cy


def main() -> None:
    if not ART.is_file():
        raise SystemExit(f"missing art: {ART}")
    blob = ART.read_bytes()
    md5, md5ext, cx, cy, w, h = png_asset(blob)
    print(f"art {ART.name} {w}x{h} md5={md5} rot=({cx},{cy}) br=2")

    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    preview = next(t for t in data["targets"] if t["name"] == SPRITE)
    assets[md5ext] = blob

    old_md5s: list[str] = []
    for c in preview["costumes"]:
        name = c["name"]
        if name in REPLACE:
            old_md5s.append(c.get("md5ext", ""))
            set_costume_png(c, md5, md5ext, cx, cy)
            print(f"  {name} → {md5ext}")
        else:
            print(f"  {name} left ({c.get('md5ext')})")

    # Keep currentCostume pointing at Preview3 if present
    names = [c["name"] for c in preview["costumes"]]
    if "Preview3" in names:
        preview["currentCostume"] = names.index("Preview3")
        print(f"  currentCostume → Preview3 (index {preview['currentCostume']})")

    # Drop unused old SVG assets if nothing else references them
    used: set[str] = set()
    for t in data["targets"]:
        for c in t.get("costumes", []):
            if c.get("md5ext"):
                used.add(c["md5ext"])
        for s in t.get("sounds", []):
            if s.get("md5ext"):
                used.add(s["md5ext"])
    removed = 0
    for old in old_md5s:
        if old and old not in used and old in assets:
            del assets[old]
            removed += 1
            print(f"  removed unused asset {old}")
    print(f"  purged {removed} old preview assets")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(data, separators=(",", ":")))
        for name, blob2 in sorted(assets.items()):
            z.writestr(name, blob2)
    SB3.write_bytes(buf.getvalue())
    print(f"wrote {SB3} ({SB3.stat().st_size} bytes)")

    with zipfile.ZipFile(SB3, "r") as z:
        data2 = json.loads(z.read("project.json"))
        prev = next(t for t in data2["targets"] if t["name"] == SPRITE)
        for c in prev["costumes"]:
            md = c["md5ext"]
            raw = z.read(md)
            im = Image.open(io.BytesIO(raw))
            print(
                f"  verify {c['name']}: {md} {im.size} "
                f"br={c.get('bitmapResolution')} fmt={c.get('dataFormat')} "
                f"rot=({c.get('rotationCenterX')},{c.get('rotationCenterY')})"
            )
            assert c.get("bitmapResolution") == 2
            assert im.size == (w, h)
    print("DONE")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Mildly downscale large PNG costumes inside sprunki-base.sb3.

Rules:
- Do not touch SVG costumes.
- Preview / intro art (sprite name Preview, or 1280x960 PNGs): resize to 960x720,
  keep bitmapResolution=2, set rotation centers to w/2, h/2.
- Other PNG costumes: if max(width, height) > 360, scale so max side == 360.
- LANCZOS, preserve alpha (RGBA PNG). No palette crush / no JPEG.
- Recompute md5ext when bytes change; update costume refs; drop orphaned assets.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_bg_pipeline import fill_interior_alpha_holes  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
CHAR_MAX = 360
INTRO_SIZE = (960, 720)


def md5ext_for(data: bytes, ext: str) -> str:
    return hashlib.md5(data).hexdigest() + "." + ext


def scale_to_max(w: int, h: int, max_side: int) -> tuple[int, int]:
    m = max(w, h)
    if m <= max_side:
        return w, h
    scale = max_side / m
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    return nw, nh


def encode_png(im: Image.Image) -> bytes:
    if im.mode not in ("RGBA", "RGB", "LA", "L"):
        im = im.convert("RGBA")
    elif im.mode == "RGB":
        # keep RGB if no alpha needed, but characters usually have alpha
        pass
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def main() -> int:
    if not SB3.exists():
        print(f"missing {SB3}", file=sys.stderr)
        return 1

    with zipfile.ZipFile(SB3, "r") as zin:
        namelist = zin.namelist()
        pj = json.loads(zin.read("project.json"))
        raw_assets = {n: zin.read(n) for n in namelist if n != "project.json"}

    # Group costume refs by current md5ext (PNG only)
    groups: dict[str, list[tuple[dict, dict]]] = {}
    for target in pj.get("targets", []):
        for costume in target.get("costumes", []):
            md5 = costume.get("md5ext") or ""
            if not md5.endswith(".png"):
                continue
            groups.setdefault(md5, []).append((target, costume))

    print(f"unique PNG costume assets: {len(groups)}")
    new_assets: dict[str, bytes] = dict(raw_assets)  # start with all; replace/delete as needed
    bytes_before = 0
    bytes_after = 0
    changed = 0
    skipped = 0
    orphaned: set[str] = set()

    for old_md5, refs in sorted(groups.items()):
        data = raw_assets.get(old_md5)
        if data is None:
            print(f"WARN missing {old_md5}", file=sys.stderr)
            continue
        bytes_before += len(data)
        im = Image.open(io.BytesIO(data))
        im.load()
        w, h = im.size

        # Decide target size
        is_preview = any(t.get("name") == "Preview" for t, _ in refs)
        is_intro_dims = (w, h) == (1280, 960)
        if is_preview or is_intro_dims:
            tw, th = INTRO_SIZE
            reason = "intro->960x720"
        elif max(w, h) > CHAR_MAX:
            tw, th = scale_to_max(w, h, CHAR_MAX)
            reason = f"char->max{CHAR_MAX}"
        else:
            # keep as-is
            bytes_after += len(data)
            skipped += 1
            continue

        if (tw, th) == (w, h):
            bytes_after += len(data)
            skipped += 1
            continue

        # Preserve alpha carefully
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        resized = im.resize((tw, th), Image.Resampling.LANCZOS)
        resized = fill_interior_alpha_holes(resized)
        new_data = encode_png(resized)
        new_md5 = md5ext_for(new_data, "png")
        sx = tw / w
        sy = th / h

        for target, costume in refs:
            costume["md5ext"] = new_md5
            costume["assetId"] = new_md5.rsplit(".", 1)[0]
            if "dataFormat" in costume:
                costume["dataFormat"] = "png"
            # Keep br=2 when dimensions remain even / suitable for 2x stage art
            br = costume.get("bitmapResolution") or 1
            if br == 2 and (tw % 2 == 0) and (th % 2 == 0):
                costume["bitmapResolution"] = 2
            # Rotation centers
            if is_preview or is_intro_dims:
                costume["rotationCenterX"] = tw / 2
                costume["rotationCenterY"] = th / 2
            else:
                rx = costume.get("rotationCenterX")
                ry = costume.get("rotationCenterY")
                if isinstance(rx, (int, float)):
                    costume["rotationCenterX"] = rx * sx
                if isinstance(ry, (int, float)):
                    costume["rotationCenterY"] = ry * sy

        # Replace asset
        if old_md5 in new_assets:
            del new_assets[old_md5]
            orphaned.add(old_md5)
        new_assets[new_md5] = new_data
        bytes_after += len(new_data)
        changed += 1
        if changed <= 8:
            print(
                f"{reason}: {refs[0][0].get('name')}/{refs[0][1].get('name')} "
                f"{w}x{h} -> {tw}x{th} ({len(data)} -> {len(new_data)})"
            )

    # Drop any assets no longer referenced
    referenced = set()
    for target in pj.get("targets", []):
        for sound in target.get("sounds", []):
            if sound.get("md5ext"):
                referenced.add(sound["md5ext"])
        for costume in target.get("costumes", []):
            if costume.get("md5ext"):
                referenced.add(costume["md5ext"])

    kept = {}
    for name, data in new_assets.items():
        if name.endswith((".png", ".svg", ".wav", ".mp3")):
            if name in referenced:
                kept[name] = data
            else:
                orphaned.add(name)
        else:
            kept[name] = data
    new_assets = kept

    missing = sorted(referenced - set(new_assets.keys()))
    if missing:
        print(f"ERROR missing refs: {missing[:10]}", file=sys.stderr)
        return 1

    out_tmp = SB3.with_suffix(".sb3.tmp")
    with zipfile.ZipFile(out_tmp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("project.json", json.dumps(pj, ensure_ascii=False, separators=(",", ":")))
        for name in sorted(new_assets.keys()):
            zout.writestr(name, new_assets[name])
    out_tmp.replace(SB3)

    saved = bytes_before - bytes_after
    pct = (100.0 * saved / bytes_before) if bytes_before else 0.0
    print(
        f"done: changed={changed} skipped={skipped} orphans_dropped={len(orphaned)} "
        f"PNG {bytes_before} -> {bytes_after} (-{saved}, {pct:.1f}%), "
        f"sb3 now {SB3.stat().st_size} bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

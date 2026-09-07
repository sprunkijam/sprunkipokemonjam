#!/usr/bin/env python3
"""Redo all custom sprites from ORIGINAL uploads with safe edge flood-fill only.

No morphological outline strengthen / heavy_wide strokes.
Also adds Sky Phase 1/2 + Icons 10 + Phase 2 sticky (b3).
"""
from __future__ import annotations

import hashlib
import io
import json
import random
import shutil
import string
import zipfile
from pathlib import Path

from PIL import Image

from safe_bg_pipeline import ATT, process_file, process_sprite

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "art"
SB3 = ROOT / "sprunki-base.sb3"
PREVIEW = ART / "_preview"
ORIGINALS = ART / "_originals"

# Character → (sprite name, icon slot, sources)
# Sources: attachment filename OR "originals:<file>" OR "backup:<file>"
CHARS = {
    "oren": {
        "sprite": "Orange (Oren)",
        "slot": "01",
        "icon": {"side": 210, "top": 8, "left_bias": 0},
        "p1": "2a5a68a132464a8a9d5cee6f12b325175d0c220f4e86e2e28f8beb5714a7ccd2.png",
        "p2": "72a3ef00b74b70bc999258acf5dba08003758366ee2f642b611476a87defadc8.png",
        "mode": "edge",
    },
    "raddy": {
        "sprite": "Red (Raddy)",
        "slot": "02",
        "icon": {"side": 250, "top": 20, "left_bias": 0},
        "p1": "94c0e21de98106291bb1baa3394631c00f09616314b424e0964cee1c4e06dc7d.png",
        "p2": "cac2dd705b68e9b0fecc5c9f21ae50b7fb5f2d0162e770ea3d6d92d51404ea26.png",
        "mode": "edge",
    },
    "vineria": {
        "sprite": "Green (Vineria)",
        "slot": "05",
        "icon": {"side": 240, "top": 8, "left_bias": -20},
        "p1": "90de50ffbbd4d8ad9f11aaa3a4670591c76af5313479088221c4e0fd9ffe8272.png",
        "p2": "237c3c583a3b0f9f531cb374f752ca4008c19d28d1066fe09d4ec1098f10af77.png",
        "mode": "edge",
    },
    "sky": {
        "sprite": "Sky blue (Sky)",
        "slot": "10",
        "icon": {"side": 220, "top": 10, "left_bias": 0},
        "p1": "1ea9665cfdfdd8f9262dd67a9ed0f65c872d3b94d53685a1c961eb40012b7ac5.png",
        "p2": "0c729dec201869e25e4d82300b36cc5704772bf31d03c2f08244d175de4a4443.png",
        "mode": "edge",
        "ensure_b3": True,
        "sticky": True,
    },
    "mrsun": {
        "sprite": "Mr. Sun",
        "slot": "11",
        "icon": {"side": 220, "top": 8, "left_bias": 0},
        "p1": "0e33eb8228f54064fca7c5c65be96b629529226f1e949a47715e1d1a21bddf87.png",
        "p2": "c9cfa19c8d9e210326e6c88a59d31e04e4ef8e21eafb8cc2b427ed0275fc9f05.png",
        "mode": "edge",
    },
    "durple": {
        "sprite": "Purple (Durple)",
        "slot": "12",
        "icon": {"side": 212, "top": 77, "left_abs": 92},
        "p1": "a5794c2a396d095632f2365819a41e357e1cb48fb2a403b3d325989a813a8e27.png",
        "p2": "a3b479f48a28e3c8261d7b427c96c4d02dcf06b6cdbd0660785788e071172e24.png",
        "mode": "edge",
    },
    "simon": {
        "sprite": "Yellow (Simon)",
        "slot": "14",
        "icon": {"side": 200, "top": 0, "left_abs": 35},
        # No raw 1254 attachment recovered — restore pre-outline cleaned originals
        "p1": None,
        "p2": None,
        "p1_local": "simon-phase1.png",
        "p2_local": "simon-phase2.png",
        "mode": "copy_originals",
        "preserve_size": 82.0,
        "p1_centers": (92.5, 144.0),
        "p2_centers": (116.0, 168.0),
    },
    "pinki": {
        "sprite": "Pink (Pinki)",
        "slot": "18",
        "icon": {"side": 210, "top": 25, "left_bias": 0},
        "p1": "67eec4cdf12d3cdfd56fe7ea37db57d2a726704afac0387165b6790da7ce5b45.png",
        "p2": "a0a04c327f50ac11bd00822628a6a4aba03bc365d54c1b43057a904fa1a7303b.png",
        "mode": "edge",
    },
    "mrblack": {
        "sprite": "Black?",
        "slot": "20",
        "icon": {"side": 240, "top": 4, "left_bias": 0},
        "p1": "bebb8a9639f3396c7b81aa070f966baec8b27c2394cbbbda2a64daa478b8ce1e.png",
        "p2": "76a49943fbe837b3e2ae9f03b1c6fa80a9cd09ea6dbab6474d20f467ccae39e7.png",
        "mode": "mrblack",
    },
}

BROADCAST_PHASE2 = ["Phase 2", "2qOY4J,K81HY:t`XJFlx"]


def uid(n: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "#%()*+,-./:;=?@[]^_{}~"
    return "".join(random.choice(alphabet) for _ in range(n))


def new_id(blocks: dict) -> str:
    for _ in range(80):
        i = uid()
        if i not in blocks:
            return i
    raise RuntimeError("id collision")


def png_md5(blob: bytes) -> tuple[str, str]:
    md5 = hashlib.md5(blob).hexdigest()
    return md5, f"{md5}.png"


def make_face_icons(phase1: Image.Image, cfg: dict, slot: str) -> dict[str, bytes]:
    w, h = phase1.size
    side = min(cfg["side"], w, h)
    top = cfg["top"]
    if "left_abs" in cfg:
        left = cfg["left_abs"]
    else:
        left = max(0, (w // 2) - side // 2 + cfg.get("left_bias", 0))
    if left + side > w:
        left = max(0, w - side)
    if top + side > h:
        top = max(0, h - side)
    face = phase1.crop((left, top, left + side, top + side))
    out: dict[str, bytes] = {}
    for name, size in ((f"{slot}-a", 68), (f"{slot}-b", 70), (f"{slot}-c", 68)):
        im = face.resize((size, size), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        out[name] = buf.getvalue()
        print(f"  icon {name} {im.size} crop=({left},{top},{side})")
    return out


def rebuild_art() -> dict[str, str]:
    """Process originals → art/*-phase*.png. Returns recovery notes."""
    PREVIEW.mkdir(parents=True, exist_ok=True)
    notes: dict[str, str] = {}
    for char, meta in CHARS.items():
        mode = meta["mode"]
        for phase, key in (("phase1", "p1"), ("phase2", "p2")):
            dest = ART / f"{char}-{phase}.png"
            if mode == "copy_originals":
                local = meta[f"{key}_local"]
                src = ORIGINALS / local
                if not src.exists():
                    src = ART / "_backup" / local
                shutil.copy2(src, dest)
                notes[f"{char}-{phase}"] = f"restored pre-outline {src}"
                print(f"COPY {dest.name} from {src}")
            else:
                att_name = meta[key]
                src = ATT / att_name
                if not src.exists():
                    raise FileNotFoundError(src)
                img = process_file(src, dest, mode=mode)
                notes[f"{char}-{phase}"] = f"attachment {att_name[:16]}… → {img.size} mode={mode}"
                print(f"PROC {dest.name} from {att_name[:20]}… → {img.size} mode={mode}")
            # preview on mid gray
            im = Image.open(dest).convert("RGBA")
            bg = Image.new("RGBA", im.size, (40, 44, 52, 255))
            bg.alpha_composite(im)
            bg.save(PREVIEW / f"{char}-{phase}-safe.png")
    return notes


def make_switch_to_b3(blocks: dict, parent: str | None) -> str:
    stmt = new_id(blocks)
    menu = new_id(blocks)
    blocks[menu] = {
        "opcode": "looks_costume",
        "next": None,
        "parent": stmt,
        "inputs": {},
        "fields": {"COSTUME": ["b3", None]},
        "shadow": True,
        "topLevel": False,
    }
    blocks[stmt] = {
        "opcode": "looks_switchcostumeto",
        "next": None,
        "parent": parent,
        "inputs": {"COSTUME": [1, menu]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    return stmt


def make_stop_other(blocks: dict, parent: str | None) -> str:
    stmt = new_id(blocks)
    blocks[stmt] = {
        "opcode": "control_stop",
        "next": None,
        "parent": parent,
        "inputs": {},
        "fields": {"STOP_OPTION": ["other scripts in sprite", None]},
        "shadow": False,
        "topLevel": False,
        "mutation": {
            "tagName": "mutation",
            "children": [],
            "hasnext": "true",
        },
    }
    return stmt


def make_phase_eq_2(blocks: dict, parent: str) -> str:
    eq = new_id(blocks)
    blocks[eq] = {
        "opcode": "operator_equals",
        "next": None,
        "parent": parent,
        "inputs": {
            "OPERAND1": [3, [12, "Phase", "Phase"], [10, ""]],
            "OPERAND2": [1, [10, "2"]],
        },
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    return eq


def make_wait0(blocks: dict, parent: str) -> str:
    stmt = new_id(blocks)
    blocks[stmt] = {
        "opcode": "control_wait",
        "next": None,
        "parent": parent,
        "inputs": {"DURATION": [1, [4, "0"]]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    return stmt


def ensure_b3_costume(target: dict, after_name: str = "idle2") -> None:
    names = [c["name"] for c in target["costumes"]]
    if "b3" in names:
        print(f"  {target['name']}: b3 costume exists")
        return
    # clone first phase1-like costume as template
    template = next(c for c in target["costumes"] if c["name"] == "idle")
    insert_at = names.index(after_name) + 1 if after_name in names else 2
    new_c = dict(template)
    new_c["name"] = "b3"
    target["costumes"].insert(insert_at, new_c)
    print(f"  {target['name']}: inserted b3 costume at {insert_at}")


def ensure_phase2_sticky(target: dict) -> None:
    blocks = target["blocks"]
    hat_id = None
    for bid, b in blocks.items():
        if not isinstance(b, dict):
            continue
        if b.get("opcode") != "event_whenbroadcastreceived":
            continue
        opt = (b.get("fields") or {}).get("BROADCAST_OPTION")
        if opt and opt[0] == "Phase 2":
            hat_id = bid
            break
    if hat_id is None:
        hat_id = new_id(blocks)
        blocks[hat_id] = {
            "opcode": "event_whenbroadcastreceived",
            "next": None,
            "parent": None,
            "inputs": {},
            "fields": {"BROADCAST_OPTION": BROADCAST_PHASE2},
            "shadow": False,
            "topLevel": True,
            "x": 100,
            "y": 100,
        }
        print(f"  {target['name']}: created Phase 2 hat")

    hat = blocks[hat_id]
    # prefix switch b3 + stop if missing
    nxt = hat.get("next")
    already_prefix = False
    if nxt and isinstance(blocks.get(nxt), dict):
        nb = blocks[nxt]
        if nb.get("opcode") == "looks_switchcostumeto":
            cin = nb.get("inputs", {}).get("COSTUME")
            if isinstance(cin, list) and len(cin) >= 2 and isinstance(cin[1], str):
                menu = blocks.get(cin[1])
                if isinstance(menu, dict) and (menu.get("fields") or {}).get("COSTUME", [None])[0] == "b3":
                    stop = nb.get("next")
                    if stop and isinstance(blocks.get(stop), dict) and blocks[stop].get("opcode") == "control_stop":
                        already_prefix = True
    if not already_prefix:
        old_next = hat.get("next")
        switch_id = make_switch_to_b3(blocks, hat_id)
        stop_id = make_stop_other(blocks, switch_id)
        blocks[switch_id]["next"] = stop_id
        blocks[stop_id]["next"] = old_next
        hat["next"] = switch_id
        if old_next and old_next in blocks and isinstance(blocks[old_next], dict):
            blocks[old_next]["parent"] = stop_id
        print(f"  {target['name']}: Phase 2 → switch b3 → stop others")
    else:
        print(f"  {target['name']}: Phase 2 prefix OK")

    # sticky forever
    cur = hat_id
    seen = set()
    last = hat_id
    while cur and cur not in seen:
        seen.add(cur)
        b = blocks[cur]
        if not isinstance(b, dict):
            break
        if b.get("opcode") == "control_forever":
            print(f"  {target['name']}: sticky forever already present")
            return
        last = cur
        cur = b.get("next")

    forever_id = new_id(blocks)
    if_id = new_id(blocks)
    eq_id = make_phase_eq_2(blocks, if_id)
    switch_id = make_switch_to_b3(blocks, if_id)
    wait_id = make_wait0(blocks, forever_id)
    blocks[if_id] = {
        "opcode": "control_if",
        "next": wait_id,
        "parent": forever_id,
        "inputs": {"CONDITION": [2, eq_id], "SUBSTACK": [2, switch_id]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    blocks[forever_id] = {
        "opcode": "control_forever",
        "next": None,
        "parent": last if last != hat_id else hat_id,
        "inputs": {"SUBSTACK": [2, if_id]},
        "fields": {},
        "shadow": False,
        "topLevel": False,
    }
    blocks[last]["next"] = forever_id
    print(f"  {target['name']}: appended sticky forever")


def assign_costumes(target: dict, p1: tuple[bytes, str, str], p2: tuple[bytes, str, str] | None, meta: dict) -> None:
    im1 = Image.open(io.BytesIO(p1[0]))
    im2 = Image.open(io.BytesIO(p2[0])) if p2 else None
    for c in target["costumes"]:
        name = c["name"]
        if name in ("bar", "idle sad"):
            continue
        if name == "b3" or "???" in name:
            if p2 is None:
                continue
            _, md5, ext = p2
            c["assetId"] = md5
            c["md5ext"] = ext
            c["dataFormat"] = "png"
            c["bitmapResolution"] = 2
            if meta.get("p2_centers"):
                c["rotationCenterX"], c["rotationCenterY"] = meta["p2_centers"]
            else:
                c["rotationCenterX"] = im2.size[0] / 2
                c["rotationCenterY"] = im2.size[1] / 2
            print(f"  {target['name']}/{name} -> phase2 {ext[:12]}… cx={c['rotationCenterX']}")
        elif name in ("idle", "idle2") or (name.startswith("anim") and "???" not in name):
            _, md5, ext = p1
            c["assetId"] = md5
            c["md5ext"] = ext
            c["dataFormat"] = "png"
            c["bitmapResolution"] = 2
            if meta.get("p1_centers"):
                c["rotationCenterX"], c["rotationCenterY"] = meta["p1_centers"]
            else:
                c["rotationCenterX"] = im1.size[0] / 2
                c["rotationCenterY"] = im1.size[1] / 2
            print(f"  {target['name']}/{name} -> phase1 {ext[:12]}… cx={c['rotationCenterX']}")


def reembed(icon_pngs: dict[str, bytes]) -> None:
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    # Preserve Simon size before edits
    simon = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    simon_size_before = simon.get("size")

    # Snapshot block graphs for non-sky customs to ensure we don't rewrite scripts
    # (we only touch Sky sticky; others keep existing Phase 2 scripts)

    art_blobs: dict[str, tuple[bytes, str, str]] = {}
    for char in CHARS:
        for phase in ("phase1", "phase2"):
            p = ART / f"{char}-{phase}.png"
            if not p.exists():
                continue
            blob = p.read_bytes()
            md5, md5ext = png_md5(blob)
            art_blobs[f"{char}-{phase}"] = (blob, md5, md5ext)
            assets[md5ext] = blob

    for char, meta in CHARS.items():
        target = next(t for t in data["targets"] if t["name"] == meta["sprite"])
        if meta.get("ensure_b3"):
            ensure_b3_costume(target)
        if meta.get("sticky"):
            ensure_phase2_sticky(target)
        if meta.get("preserve_size") is not None:
            target["size"] = float(meta["preserve_size"])
            print(f"  {meta['sprite']} size={target['size']}")

        p1 = art_blobs.get(f"{char}-phase1")
        p2 = art_blobs.get(f"{char}-phase2")
        if p1 is None:
            print(f"  WARN missing phase1 for {char}")
            continue
        assign_costumes(target, p1, p2, meta)

    # Icons
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
    for c in icons["costumes"]:
        if c["name"] not in icon_pngs:
            continue
        blob = icon_pngs[c["name"]]
        md5, md5ext = png_md5(blob)
        assets[md5ext] = blob
        im = Image.open(io.BytesIO(blob))
        c["assetId"] = md5
        c["md5ext"] = md5ext
        c["dataFormat"] = "png"
        c["bitmapResolution"] = 2
        c["rotationCenterX"] = im.size[0] / 2
        c["rotationCenterY"] = im.size[1] / 2
        print(f"  Icons/{c['name']} -> {md5ext[:12]}… {im.size}")

    # Verify Simon size
    simon2 = next(t for t in data["targets"] if t["name"] == "Yellow (Simon)")
    assert float(simon2.get("size")) == 82.0, simon2.get("size")
    print(f"  Simon size OK (was {simon_size_before}, now {simon2.get('size')})")

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
    print(f"wrote {SB3} ({SB3.stat().st_size} bytes)")


def main() -> None:
    print("=== 1) Rebuild art from originals (edge flood-fill ONLY) ===")
    notes = rebuild_art()
    print("recovery:")
    for k, v in notes.items():
        print(f"  {k}: {v}")

    print("=== 2) Face icons from Phase 1 ===")
    icon_pngs: dict[str, bytes] = {}
    for char, meta in CHARS.items():
        p1 = Image.open(ART / f"{char}-phase1.png")
        icon_pngs.update(make_face_icons(p1, meta["icon"], meta["slot"]))

    print("=== 3) Re-embed sb3 ===")
    reembed(icon_pngs)
    print("DONE")


if __name__ == "__main__":
    main()

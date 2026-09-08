#!/usr/bin/env python3
"""Add Lime (OWAKCX) Phase 2 art → b3 + anim???*; sticky Phase 2; drop → b3.

Source has light gray / white bg — keep-mask carefully (chromatic / non-bg seeds,
grow through dark outlines; knock only exterior near-white/gray).
Snap near-white fringe on outline edges to alpha 0 (no milky halo).
Icons 09 stay Phase 1 face. Size keep ~50. Bounce frames via apply_bounce_frames.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_phase2_sticky import (  # noqa: E402
    TARGET_H,
    append_sticky_forever,
    ensure_phase2_prefix,
    png_asset,
    rebuild_switch_costume,
    set_costume_png,
)
from safe_bg_pipeline import corner_median_rgb, crop_and_scale  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
ART_P1 = ROOT / "art" / "owakcx-phase1.png"
ART_P2 = ROOT / "art" / "owakcx-phase2.png"
PREV = ROOT / "art" / "_preview"
OUT_CHECK = Path("/workspace/owakcx-p2-eyes-check.png")
SRC_P2 = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments/"
    "cfaff94e57f9410a4778b60bf3809986a24fb34d68b457914ff0702c2f43fcb5.png"
)

SPRITE = "Lime (OWAKCX)"
POLO_ID = "[|;9JikY^{|VLgG75_49"  # Polo Im On RN
OWAKCX_SIZE = 50.0
NEAR_TOL = 40.0


def _dilate_bool(mask: np.ndarray, iters: int = 1) -> np.ndarray:
    out = mask.copy()
    for _ in range(iters):
        grown = out.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                grown |= np.roll(np.roll(out, dy, 0), dx, 1)
        out = grown
    return out


def _exterior_transparent(a: np.ndarray) -> np.ndarray:
    """Transparent pixels reachable from the image border (outer void only)."""
    h, w = a.shape
    exterior = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()

    def try_seed(y: int, x: int) -> None:
        if a[y, x] == 0 and not exterior[y, x]:
            exterior[y, x] = True
            q.append((y, x))

    for x in range(w):
        try_seed(0, x)
        try_seed(h - 1, x)
    for y in range(h):
        try_seed(y, 0)
        try_seed(y, w - 1)
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not exterior[ny, nx] and a[ny, nx] == 0:
                exterior[ny, nx] = True
                q.append((ny, nx))
    return exterior


def snap_white_fringe(out: np.ndarray) -> np.ndarray:
    """Snap near-white fringe on the OUTER silhouette edge only → alpha 0.

    Interior whites (eye sclera, teeth) stay even if adjacent to small holes.
    Does not eat solid black outline (low RGB). A few passes clear LANCZOS
    milky halos on the outer edge.
    """
    for _ in range(3):
        a = out[:, :, 3]
        rgb = out[:, :, :3].astype(np.int16)
        mx = rgb.max(axis=2)
        mn = rgb.min(axis=2)
        ch = mx - mn
        fringe_cand = (
            ((mn >= 175) & (ch <= 40))
            | ((mn >= 200) & (ch <= 55))
            | ((mx >= 230) & (mn >= 160) & (ch <= 50))
        ) & (a > 0)

        exterior_t = _exterior_transparent(a)
        touch_outer = np.zeros_like(exterior_t)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                touch_outer |= np.roll(np.roll(exterior_t, dy, 0), dx, 1)
        dark = mx < 90
        snap = fringe_cand & touch_outer & ~dark
        if not snap.any():
            break
        out[snap, 3] = 0
    return out


def prep_owakcx_white_bg(im: Image.Image) -> Image.Image:
    """Keep-mask for light gray/white bg: seed non-bg + chromatic; grow dark outlines."""
    arr = np.array(im.convert("RGBA"))
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3].astype(np.int16)
    a = arr[:, :, 3]
    bg = corner_median_rgb(arr)
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    ch = mx - mn
    diff = np.abs(rgb.astype(np.float32) - bg.astype(np.float32)).max(axis=2)
    near = diff <= NEAR_TOL
    chromatic = (ch > 25) & (mx > 40) & (a > 30)
    seeds = ((~near) & (a > 30)) | chromatic

    keep = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    ys, xs = np.where(seeds)
    for y, x in zip(ys.tolist(), xs.tolist()):
        keep[y, x] = True
        q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not keep[ny, nx]:
                # grow through non-bg OR dark outline ink
                if a[ny, nx] > 20 and (not near[ny, nx] or mx[ny, nx] < 90):
                    keep[ny, nx] = True
                    q.append((ny, nx))

    pre_dilate = keep.copy()
    keep = _dilate_bool(keep, 2)
    keep &= a > 0
    # Dilate must NOT pull exterior white/gray into KEEP (halo source).
    # Only allow dilated pixels that are dark outline-ish or chromatic / already kept.
    near_white_px = (mn >= 175) & (ch <= 40)
    light_bgish = near | near_white_px
    keep &= pre_dilate | ~light_bgish | (mx < 90)

    # Interior whites (eye sclera, teeth, etc.): enclosed ~KEEP pockets stay.
    # Flood exterior from border through non-KEEP; anything left is a hole → KEEP.
    exterior = np.zeros((h, w), dtype=bool)
    q_ext: deque[tuple[int, int]] = deque()

    def seed_ext(y: int, x: int) -> None:
        if keep[y, x] or exterior[y, x]:
            return
        exterior[y, x] = True
        q_ext.append((y, x))

    for x in range(w):
        seed_ext(0, x)
        seed_ext(h - 1, x)
    for y in range(h):
        seed_ext(y, 0)
        seed_ext(y, w - 1)
    while q_ext:
        y, x = q_ext.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not exterior[ny, nx] and not keep[ny, nx]:
                exterior[ny, nx] = True
                q_ext.append((ny, nx))
    holes = (~keep) & (~exterior) & (a > 0)
    keep |= holes
    print(f"  interior hole pixels restored into KEEP: {int(holes.sum())}")

    out = arr.copy()
    out[~keep, 3] = 0
    # Edge-flood leftover near-white exterior (not in keep)
    knock = np.zeros((h, w), dtype=bool)
    q2: deque[tuple[int, int]] = deque()
    near_white = near & (a > 0) & ~keep

    def try_seed(y: int, x: int) -> None:
        if knock[y, x]:
            return
        if out[y, x, 3] == 0 or near_white[y, x]:
            knock[y, x] = True
            q2.append((y, x))

    for x in range(w):
        try_seed(0, x)
        try_seed(h - 1, x)
    for y in range(h):
        try_seed(y, 0)
        try_seed(y, w - 1)
    ys, xs = np.where(out[:, :, 3] == 0)
    for y, x in zip(ys.tolist(), xs.tolist()):
        try_seed(y, x)
    while q2:
        y, x = q2.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not knock[ny, nx]:
                if near_white[ny, nx] or out[ny, nx, 3] == 0:
                    knock[ny, nx] = True
                    q2.append((ny, nx))
    out[knock & ~keep, 3] = 0

    out = snap_white_fringe(out)
    img = crop_and_scale(Image.fromarray(out, "RGBA"), TARGET_H)
    # LANCZOS creates milky AA — snap again after scale
    arr2 = snap_white_fringe(np.array(img.convert("RGBA")))
    return Image.fromarray(arr2, "RGBA")




def ensure_b3(target: dict) -> None:
    names = [c["name"] for c in target["costumes"]]
    if "b3" in names:
        print("  b3 already present")
        return
    horror = next(
        (c for c in target["costumes"] if "???" in c["name"]),
        None,
    )
    if horror is None:
        # clone idle as template metadata
        horror = next(c for c in target["costumes"] if c["name"] == "idle")
    idx = names.index("idle2") + 1 if "idle2" in names else 2
    new_c = {k: horror[k] for k in horror}
    new_c["name"] = "b3"
    target["costumes"].insert(idx, new_c)
    print(f"  inserted b3 at {idx}")


def ensure_phase2_anim_slots(target: dict, n: int = 5) -> None:
    """Ensure anim??? … anim???{n-1} exist (rename ???1→??? if needed)."""
    by_name = {c["name"]: c for c in target["costumes"]}
    # Prefer canonical names: anim???, anim???2, ...
    desired = ["anim???"] + [f"anim???{i}" for i in range(2, n + 1)]
    # If only anim???1 exists, rename to anim???
    if "anim???" not in by_name and "anim???1" in by_name:
        by_name["anim???1"]["name"] = "anim???"
        by_name["anim???"] = by_name.pop("anim???1")
        print("  renamed anim???1 → anim???")
    template = by_name.get("anim???") or by_name.get("b3") or target["costumes"][0]
    for name in desired:
        if name in by_name:
            continue
        c = {k: template[k] for k in template}
        c["name"] = name
        target["costumes"].append(c)
        by_name[name] = c
        print(f"  inserted costume slot {name}")


def assign_phase2(target: dict, p2: bytes, assets: dict) -> None:
    md2, ext2, cx2, cy2 = png_asset(p2)
    assets[ext2] = p2
    for c in target["costumes"]:
        name = c["name"]
        if name == "b3" or "???" in name:
            set_costume_png(c, md2, ext2, cx2, cy2)
            print(f"  costume {name} → phase2 {ext2}")


def checker(img: Image.Image, cell: int = 16) -> Image.Image:
    ww, hh = img.size
    bg = Image.new("RGBA", (ww, hh))
    px = bg.load()
    for y in range(hh):
        for x in range(ww):
            c = 180 if (x // cell + y // cell) % 2 == 0 else 220
            px[x, y] = (c, c, c, 255)
    bg.alpha_composite(img)
    return bg


def main() -> None:
    PREV.mkdir(parents=True, exist_ok=True)
    assert SRC_P2.exists(), SRC_P2
    assert ART_P1.exists(), ART_P1

    print("1) Prep OWAKCX Phase 2 (keep-mask + interior whites; outer fringe snap only)")
    p2 = prep_owakcx_white_bg(Image.open(SRC_P2))
    ART_P2.parent.mkdir(parents=True, exist_ok=True)
    p2.save(ART_P2, "PNG")
    p2_bytes = ART_P2.read_bytes()
    print(f"  saved {ART_P2.name} {p2.size} ({len(p2_bytes)} bytes)")
    # Dual preview: dark + checker side-by-side (fringe visible if any)
    pad = 16
    dark = Image.new("RGBA", (p2.width + 2 * pad, p2.height + 2 * pad), (20, 20, 24, 255))
    dark.paste(p2, (pad, pad), p2)
    chk = checker(p2)
    chk_pad = Image.new("RGBA", (chk.width + 2 * pad, chk.height + 2 * pad), (40, 40, 44, 255))
    chk_pad.paste(chk, (pad, pad))
    gap = 12
    combo = Image.new(
        "RGBA",
        (dark.width + gap + chk_pad.width, max(dark.height, chk_pad.height)),
        (12, 12, 14, 255),
    )
    combo.paste(dark, (0, 0))
    combo.paste(chk_pad, (dark.width + gap, 0))
    combo.save(PREV / "owakcx-phase2-dark-checker.png")
    combo.save(OUT_CHECK)
    dark.save(PREV / "owakcx-phase2-on-dark.png")
    chk.save(PREV / "owakcx-phase2-checker.png")
    print(f"  wrote {OUT_CHECK} (dark|checker)")

    print("2) Load sb3")
    with zipfile.ZipFile(SB3, "r") as z:
        data = json.loads(z.read("project.json"))
        assets = {n: z.read(n) for n in z.namelist() if n != "project.json"}

    target = next(t for t in data["targets"] if t["name"] == SPRITE)
    print(f"3) OWAKCX size={target.get('size')} keep {OWAKCX_SIZE}")
    target["size"] = float(OWAKCX_SIZE)

    print("4) Ensure b3 + phase2 anim slots; assign Phase 2 art")
    ensure_b3(target)
    ensure_phase2_anim_slots(target, n=5)
    assign_phase2(target, p2_bytes, assets)

    print("5) Icons 09 left as Phase 1 face")
    icons = next(t for t in data["targets"] if t["name"] == "Icons")
    for c in icons["costumes"]:
        if c["name"].startswith("09"):
            print(f"  Icons {c['name']} keep {c.get('md5ext')} fmt={c.get('dataFormat')}")

    print("6) Phase 2 sticky + Switch Costume guards")
    hat = ensure_phase2_prefix(target)
    append_sticky_forever(target, hat)
    rebuild_switch_costume(target, POLO_ID)

    print("7) Write sb3")
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

    with zipfile.ZipFile(SB3, "r") as z:
        data2 = json.loads(z.read("project.json"))
    lime = next(t for t in data2["targets"] if t["name"] == SPRITE)
    assert lime.get("size") == OWAKCX_SIZE
    names = [c["name"] for c in lime["costumes"]]
    assert "b3" in names
    idle_md = next(c["md5ext"] for c in lime["costumes"] if c["name"] == "idle")
    b3_md = next(c["md5ext"] for c in lime["costumes"] if c["name"] == "b3")
    assert idle_md != b3_md
    print(f"VERIFY size={lime.get('size')} idle≠b3 ({idle_md[:8]}… vs {b3_md[:8]}…)")

    print("8) Bounce-pad frames for OWAKCX (b3 + anim???*)")
    from apply_bounce_frames import apply_bounce_to_sb3  # noqa: E402
    apply_bounce_to_sb3(SB3, chars=["owakcx"])
    print("DONE")


if __name__ == "__main__":
    main()

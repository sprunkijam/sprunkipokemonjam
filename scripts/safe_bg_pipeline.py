#!/usr/bin/env python3
"""Safe background removal for black-bg cartoon sprites.

Default `edge` mode for black backgrounds uses chromatic KEEP-mask:
  1) Seed KEEP from chromatic / non-near-black / accent pixels
  2) BFS-grow KEEP through ALL connected opaque pixels (incl. pure black outlines)
  3) Dilate KEEP 1–2px for AA fringe
  4) Knock to alpha 0 only pixels NOT in KEEP (exterior black bg)

Never flood near-bg from borders through black outline strokes.
White-bg arts keep old near-white edge flood.
Mr Black uses specialized prep_mrblack (same keep idea, accent-seeded).
NEVER morphological outline strengthen / heavy_wide.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

TARGET_H = 400
ATT = Path(
    "/home/box/agent-data/agents/26930d12-2d2b-4e7f-a00a-1a9f12adcda7/attachments"
)

# Keep-mask thresholds (tuned for 1254 black-bg cartoons)
MAX_CHANNEL_KEEP = 40  # max RGB channel > this → seed
CHROMA_KEEP = 25  # max-min > this → seed
SEED_ALPHA = 30
GROW_ALPHA = 20
DILATE_ITERS = 2  # 1–2px AA fringe


def corner_median_rgb(arr: np.ndarray, s: int = 12) -> np.ndarray:
    h, w = arr.shape[:2]
    patches = [
        arr[0:s, 0:s, :3],
        arr[0:s, w - s : w, :3],
        arr[h - s : h, 0:s, :3],
        arr[h - s : h, w - s : w, :3],
    ]
    samples = np.concatenate([p.reshape(-1, 3) for p in patches], axis=0)
    return np.median(samples, axis=0)


def near_bg(rgb: np.ndarray, bg: np.ndarray, tol: float) -> np.ndarray:
    diff = np.abs(rgb.astype(np.float32) - bg.astype(np.float32)).max(axis=2)
    return diff <= tol


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


def keep_mask_knock(
    im: Image.Image,
    *,
    dilate_iters: int = DILATE_ITERS,
    max_channel: int = MAX_CHANNEL_KEEP,
    chroma: int = CHROMA_KEEP,
) -> Image.Image:
    """Chromatic-seed KEEP, grow through opaque (incl. black outlines), knock exterior."""
    arr = np.array(im.convert("RGBA"))
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3].astype(np.int16)
    a = arr[:, :, 3]

    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    ch = mx - mn

    # Accents: red / white / yellow / bright chromatic
    red = (rgb[:, :, 0] > 100) & (rgb[:, :, 1] < 100) & (rgb[:, :, 2] < 100) & (a > SEED_ALPHA)
    white = (mn > 180) & (a > SEED_ALPHA)
    yellow = (rgb[:, :, 0] > 140) & (rgb[:, :, 1] > 100) & (rgb[:, :, 2] < 120) & (a > SEED_ALPHA)
    non_near_black = (mx > max_channel) & (a > SEED_ALPHA)
    chromatic = (ch > chroma) & (mx > 30) & (a > SEED_ALPHA)
    seeds = red | white | yellow | non_near_black | chromatic

    keep = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    ys, xs = np.where(seeds)
    for y, x in zip(ys.tolist(), xs.tolist()):
        keep[y, x] = True
        q.append((y, x))

    # BFS grow through ALL connected opaque pixels INCLUDING pure black
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not keep[ny, nx]:
                if a[ny, nx] > GROW_ALPHA:
                    keep[ny, nx] = True
                    q.append((ny, nx))

    if dilate_iters > 0:
        keep = _dilate_bool(keep, dilate_iters)
        keep &= a > 0

    out = arr.copy()
    out[~keep, 3] = 0

    # Optional: also edge-flood pure exterior bg that's already outside KEEP
    # (cleans any leftover near-black islands not connected to character)
    bg = corner_median_rgb(arr)
    bg_lum = float(0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2])
    if bg_lum < 80:
        # only knock near-black that is NOT keep and edge-reachable
        near_black = (mx <= 28) & (a > 0) & ~keep
        knock = np.zeros((h, w), dtype=bool)
        q2: deque[tuple[int, int]] = deque()

        def try_seed(y: int, x: int) -> None:
            if knock[y, x]:
                return
            if out[y, x, 3] == 0 or near_black[y, x]:
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
                    if near_black[ny, nx] or out[ny, nx, 3] == 0:
                        knock[ny, nx] = True
                        q2.append((ny, nx))
        out[knock & ~keep, 3] = 0

    return Image.fromarray(out, "RGBA")


def edge_flood_knock_white(
    im: Image.Image,
    *,
    tol: float | None = None,
    feather_px: int = 1,
) -> Image.Image:
    """Near-white edge flood for white-bg arts only."""
    arr = np.array(im.convert("RGBA"))
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3]
    a = arr[:, :, 3]
    bg = corner_median_rgb(arr)
    if tol is None:
        tol = 42.0

    is_empty = a == 0
    is_bgish = near_bg(rgb, bg, tol) & (a > 0)

    knock = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()

    def try_seed(y: int, x: int) -> None:
        if knock[y, x]:
            return
        if is_empty[y, x] or is_bgish[y, x]:
            knock[y, x] = True
            q.append((y, x))

    for x in range(w):
        try_seed(0, x)
        try_seed(h - 1, x)
    for y in range(h):
        try_seed(y, 0)
        try_seed(y, w - 1)
    ys, xs = np.where(is_empty)
    for y, x in zip(ys.tolist(), xs.tolist()):
        try_seed(y, x)

    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not knock[ny, nx]:
                if is_bgish[ny, nx] or is_empty[ny, nx]:
                    knock[ny, nx] = True
                    q.append((ny, nx))

    out = arr.copy()
    out[knock, 3] = 0

    if feather_px > 0:
        a2 = out[:, :, 3]
        fringe = np.zeros((h, w), dtype=bool)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                fringe |= np.roll(np.roll(knock, dy, 0), dx, 1)
        fringe &= a2 > 0
        close = near_bg(out[:, :, :3], bg, tol + 20)
        soft = fringe & close & (a2 < 250)
        out[soft, 3] = 0

    return Image.fromarray(out, "RGBA")


# Back-compat alias: old name now dispatches by bg type in process_sprite
def edge_flood_knock(im: Image.Image, **kwargs) -> Image.Image:
    """Legacy entry: black bg → keep-mask; white bg → near-white flood."""
    arr = np.array(im.convert("RGBA"))
    bg = corner_median_rgb(arr)
    bg_lum = float(0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2])
    if bg_lum < 80:
        return keep_mask_knock(im)
    return edge_flood_knock_white(im, **kwargs)


def prep_mrblack(im: Image.Image) -> Image.Image:
    """Accent-seeded keep for black-on-black; only knock edge-reachable pure bg black."""
    arr = np.array(im.convert("RGBA"))
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3].astype(np.int16)
    a = arr[:, :, 3]

    red = (rgb[:, :, 0] > 100) & (rgb[:, :, 1] < 100) & (rgb[:, :, 2] < 100) & (a > 30)
    white = (rgb.min(axis=2) > 180) & (a > 30)
    chromatic = (
        (rgb.max(axis=2) - rgb.min(axis=2) > 35)
        & (rgb.max(axis=2) > 45)
        & (a > 30)
    )
    seeds = red | white | chromatic

    body = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    ys, xs = np.where(seeds)
    for y, x in zip(ys.tolist(), xs.tolist()):
        body[y, x] = True
        q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not body[ny, nx]:
                if a[ny, nx] > 20:
                    body[ny, nx] = True
                    q.append((ny, nx))

    keep = _dilate_bool(body, 1)
    keep &= a > 0

    near_black = (rgb.max(axis=2) <= 28) & (a > 0) & ~keep
    knock = np.zeros((h, w), dtype=bool)
    q = deque()

    def try_seed(y: int, x: int) -> None:
        if knock[y, x]:
            return
        if a[y, x] == 0 or near_black[y, x]:
            knock[y, x] = True
            q.append((y, x))

    for x in range(w):
        try_seed(0, x)
        try_seed(h - 1, x)
    for y in range(h):
        try_seed(y, 0)
        try_seed(y, w - 1)
    ys, xs = np.where(a == 0)
    for y, x in zip(ys.tolist(), xs.tolist()):
        try_seed(y, x)
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not knock[ny, nx]:
                if near_black[ny, nx] or a[ny, nx] == 0:
                    knock[ny, nx] = True
                    q.append((ny, nx))

    out = arr.copy()
    out[knock & ~keep, 3] = 0
    out[~keep, 3] = 0
    return Image.fromarray(out, "RGBA")



def fill_interior_alpha_holes(im: Image.Image) -> Image.Image:
    """Restore enclosed transparent pixels (e.g. LANCZOS downscale punch-through).

    Border-connected transparency (true exterior) is left alone. Interior holes
    get alpha=255; RGB is taken from the nearest opaque neighbor (4-connected BFS).
    """
    arr = np.array(im.convert("RGBA"))
    h, w = arr.shape[:2]
    alpha = arr[:, :, 3]
    trans = alpha == 0
    border = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()

    def seed(y: int, x: int) -> None:
        if trans[y, x] and not border[y, x]:
            border[y, x] = True
            q.append((y, x))

    for x in range(w):
        seed(0, x)
        seed(h - 1, x)
    for y in range(h):
        seed(y, 0)
        seed(y, w - 1)
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and trans[ny, nx] and not border[ny, nx]:
                border[ny, nx] = True
                q.append((ny, nx))

    holes = trans & ~border
    if not holes.any():
        return im

    # Nearest opaque RGB via multi-source BFS
    inf = h * w + 5
    dist = np.full((h, w), inf, dtype=np.int32)
    parent_r = np.zeros((h, w), dtype=np.uint8)
    parent_g = np.zeros((h, w), dtype=np.uint8)
    parent_b = np.zeros((h, w), dtype=np.uint8)
    q2: deque[tuple[int, int]] = deque()
    ys, xs = np.where(~trans)
    for y, x in zip(ys.tolist(), xs.tolist()):
        dist[y, x] = 0
        parent_r[y, x] = arr[y, x, 0]
        parent_g[y, x] = arr[y, x, 1]
        parent_b[y, x] = arr[y, x, 2]
        q2.append((y, x))
    while q2:
        y, x = q2.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and dist[ny, nx] > dist[y, x] + 1:
                dist[ny, nx] = dist[y, x] + 1
                parent_r[ny, nx] = parent_r[y, x]
                parent_g[ny, nx] = parent_g[y, x]
                parent_b[ny, nx] = parent_b[y, x]
                q2.append((ny, nx))

    out = arr.copy()
    hy, hx = np.where(holes)
    out[hy, hx, 0] = parent_r[hy, hx]
    out[hy, hx, 1] = parent_g[hy, hx]
    out[hy, hx, 2] = parent_b[hy, hx]
    out[hy, hx, 3] = 255
    return Image.fromarray(out, "RGBA")


def crop_and_scale(img: Image.Image, target_h: int = TARGET_H) -> Image.Image:
    bbox = img.split()[-1].getbbox()
    if bbox:
        l, t, r, btm = bbox
        pad = 2
        l = max(0, l - pad)
        t = max(0, t - pad)
        r = min(img.width, r + pad)
        btm = min(img.height, btm + pad)
        img = img.crop((l, t, r, btm))
    if img.height != target_h:
        nw = max(1, round(img.width * target_h / img.height))
        img = img.resize((nw, target_h), Image.Resampling.LANCZOS)
    # force interior opaque where alpha was high (avoid gray mush)
    arr = np.array(img)
    a = arr[:, :, 3]
    arr[a >= 250, 3] = 255
    return Image.fromarray(arr, "RGBA")


def try_rembg(im: Image.Image) -> Image.Image | None:
    """Optional rembg isnet-anime; returns None if unavailable or fails."""
    try:
        from rembg import remove, new_session  # type: ignore
    except Exception:
        return None
    try:
        session = new_session("isnet-anime")
        out = remove(im.convert("RGBA"), session=session)
        if not isinstance(out, Image.Image):
            out = Image.open(__import__("io").BytesIO(out)).convert("RGBA")
        return out.convert("RGBA")
    except Exception:
        return None




def prep_wenda(im: Image.Image, *, bg_tol: float = 28.0, dilate_iters: int = 2) -> Image.Image:
    """Light-gray bg + white fur (+ optional black ichor). Corner-median bg;
    seed KEEP from gold/pink/magenta/blue/black outlines/ichor/near-white fur;
    grow through non-bg; knock only exterior light-gray NOT in KEEP.
    """
    arr = np.array(im.convert("RGBA"))
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3].astype(np.int16)
    a = arr[:, :, 3]
    bg = corner_median_rgb(arr)

    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    ch = mx - mn
    lum = (0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]).astype(
        np.float32
    )
    diff = np.abs(rgb.astype(np.float32) - bg.astype(np.float32)).max(axis=2)
    near_bg = (diff <= bg_tol) & (a > 0)
    opaque = a > 30

    blackish = (mx <= 55) & opaque & ~near_bg
    gold = (rgb[:, :, 0] > 150) & (rgb[:, :, 1] > 100) & (rgb[:, :, 2] < 140) & (ch > 25) & opaque
    pink = (rgb[:, :, 0] > 140) & (rgb[:, :, 2] > 100) & (rgb[:, :, 0] > rgb[:, :, 1] + 15) & opaque
    blue = (
        (rgb[:, :, 2] > 120)
        & (rgb[:, :, 2] > rgb[:, :, 0] + 20)
        & (rgb[:, :, 2] > rgb[:, :, 1] + 10)
        & opaque
    )
    chromatic = (ch > 28) & (mx > 40) & opaque & ~near_bg
    white_fur = (mn > 200) & (diff > bg_tol) & opaque
    cream = (lum > 210) & (diff > bg_tol + 5) & opaque
    seeds = blackish | gold | pink | blue | chromatic | white_fur | cream

    keep = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    ys, xs = np.where(seeds)
    for y, x in zip(ys.tolist(), xs.tolist()):
        keep[y, x] = True
        q.append((y, x))

    growable = opaque & ~near_bg
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not keep[ny, nx]:
                if growable[ny, nx]:
                    keep[ny, nx] = True
                    q.append((ny, nx))

    if dilate_iters > 0:
        keep = _dilate_bool(keep, dilate_iters)
        keep &= a > 0

    knock = np.zeros((h, w), dtype=bool)
    q2: deque[tuple[int, int]] = deque()

    def try_seed(y: int, x: int) -> None:
        if knock[y, x]:
            return
        if a[y, x] == 0 or (near_bg[y, x] and not keep[y, x]):
            knock[y, x] = True
            q2.append((y, x))

    for x in range(w):
        try_seed(0, x)
        try_seed(h - 1, x)
    for y in range(h):
        try_seed(y, 0)
        try_seed(y, w - 1)
    ys, xs = np.where(a == 0)
    for y, x in zip(ys.tolist(), xs.tolist()):
        try_seed(y, x)
    while q2:
        y, x = q2.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not knock[ny, nx]:
                if a[ny, nx] == 0 or (near_bg[ny, nx] and not keep[ny, nx]):
                    knock[ny, nx] = True
                    q2.append((ny, nx))

    out = arr.copy()
    out[knock & ~keep, 3] = 0
    out[~keep & near_bg, 3] = 0
    wide = (diff <= bg_tol + 18) & ~keep
    out[wide, 3] = 0
    return Image.fromarray(out, "RGBA")




def keep_mask_exterior_only(
    im: Image.Image,
    *,
    bg_tol: float = 22.0,
    dilate_iters: int = 1,
) -> Image.Image:
    """Light-gray (or any) bg: knock ONLY border-connected near-bg.

    KEEP = every opaque pixel not reachable as exterior near-bg from the
    image border. Grows through dark facets / black outlines / rock interiors
    automatically — never punches enclosed interiors. No fake outline strokes.
    """
    arr = np.array(im.convert("RGBA"))
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3]
    a = arr[:, :, 3]
    bg = corner_median_rgb(arr)
    is_empty = a == 0
    is_bgish = near_bg(rgb, bg, bg_tol) & (a > 0)

    exterior = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()

    def try_seed(y: int, x: int) -> None:
        if exterior[y, x]:
            return
        if is_empty[y, x] or is_bgish[y, x]:
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
            if 0 <= ny < h and 0 <= nx < w and not exterior[ny, nx]:
                if is_empty[ny, nx] or is_bgish[ny, nx]:
                    exterior[ny, nx] = True
                    q.append((ny, nx))

    keep = (a > 0) & ~exterior
    if dilate_iters > 0:
        # pull back a thin AA fringe of near-bg adjacent to KEEP into KEEP
        keep = _dilate_bool(keep, dilate_iters) & (a > 0) & ~exterior

    out = arr.copy()
    out[~keep, 3] = 0

    # Safety: restore any remaining interior transparent holes from original RGB
    trans = out[:, :, 3] == 0
    border = np.zeros((h, w), dtype=bool)
    q2: deque[tuple[int, int]] = deque()

    def seed2(y: int, x: int) -> None:
        if trans[y, x] and not border[y, x]:
            border[y, x] = True
            q2.append((y, x))

    for x in range(w):
        seed2(0, x)
        seed2(h - 1, x)
    for y in range(h):
        seed2(y, 0)
        seed2(y, w - 1)
    while q2:
        y, x = q2.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and trans[ny, nx] and not border[ny, nx]:
                border[ny, nx] = True
                q2.append((ny, nx))
    holes = trans & ~border
    if holes.any():
        out[holes, :3] = arr[holes, :3]
        out[holes, 3] = 255

    return Image.fromarray(out, "RGBA")


def keep_mask_light_gray(
    im: Image.Image,
    *,
    bg_tol: float = 28.0,
    pure_tol: float = 8.0,
    dilate_iters: int = 2,
) -> Image.Image:
    """Light-gray bg keep-mask for Clukr/Magneton-style art.

    Edge-knock exterior near-bg; KEEP textured metal + black outlines + oil drips
    + accents; knock enclosed pure-bg islands (center gap between spheres).
    """
    base = edge_flood_knock_white(im, tol=bg_tol, feather_px=1)
    arr = np.array(base.convert("RGBA"))
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3].astype(np.int16)
    a = arr[:, :, 3]
    orig = np.array(im.convert("RGBA"))
    bg = corner_median_rgb(orig)
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    ch = mx - mn
    diff = np.abs(rgb.astype(np.float32) - bg.astype(np.float32)).max(axis=2)
    opaque = a > 30
    pure_bg = opaque & (diff <= pure_tol) & (ch <= 10)
    blackish = (mx <= 55) & opaque
    oil = (mx <= 95) & (ch <= 40) & opaque & (diff > pure_tol)
    pink = (
        (rgb[:, :, 0] > 140)
        & (rgb[:, :, 2] > 90)
        & (rgb[:, :, 0] > rgb[:, :, 1] + 8)
        & opaque
    )
    red = (
        (rgb[:, :, 0] > 120)
        & (rgb[:, :, 0] > rgb[:, :, 1] + 25)
        & (rgb[:, :, 0] > rgb[:, :, 2] + 25)
        & opaque
    )
    blue = (rgb[:, :, 2] > 100) & (rgb[:, :, 2] > rgb[:, :, 0] + 12) & opaque
    white_hi = (mn > 215) & opaque
    chromatic = (ch > 18) & (mx > 35) & opaque
    metal = (diff > pure_tol) & opaque
    seeds = blackish | oil | pink | red | blue | white_hi | chromatic | metal

    keep = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    ys, xs = np.where(seeds)
    for y, x in zip(ys.tolist(), xs.tolist()):
        keep[y, x] = True
        q.append((y, x))
    growable = opaque & ~pure_bg
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not keep[ny, nx] and growable[ny, nx]:
                keep[ny, nx] = True
                q.append((ny, nx))
    if dilate_iters:
        keep = _dilate_bool(keep, dilate_iters) & (a > 0)

    out = arr.copy()
    out[pure_bg & ~keep, 3] = 0
    out[~keep & opaque & (diff <= pure_tol + 4) & (ch <= 12), 3] = 0
    return Image.fromarray(out, "RGBA")


def process_sprite(im: Image.Image, *, mode: str = "edge") -> Image.Image:
    if mode == "mrblack":
        cleared = prep_mrblack(im)
    elif mode == "wenda":
        cleared = prep_wenda(im)
    elif mode in ("lightgray", "clukr"):
        cleared = keep_mask_light_gray(im)
    elif mode in ("gray", "exterior", "geodude"):
        cleared = keep_mask_exterior_only(im)
        return fill_interior_alpha_holes(crop_and_scale(cleared))
    elif mode == "rembg":
        rem = try_rembg(im)
        cleared = rem if rem is not None else edge_flood_knock(im)
    else:
        # default edge: keep-mask for black bg, white flood for white bg
        # optionally try rembg if installed and clearly better — skip auto for now
        cleared = edge_flood_knock(im)
    return crop_and_scale(cleared)


def process_file(src: Path, dest: Path, *, mode: str = "edge") -> Image.Image:
    im = Image.open(src)
    out = process_sprite(im, mode=mode)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest, "PNG")
    return out


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("usage: safe_bg_pipeline.py SRC DEST [edge|mrblack|rembg|wenda|lightgray|clukr|gray|exterior]")
        raise SystemExit(2)
    mode = sys.argv[3] if len(sys.argv) > 3 else "edge"
    img = process_file(Path(sys.argv[1]), Path(sys.argv[2]), mode=mode)
    print(f"wrote {sys.argv[2]} {img.size} mode={mode}")

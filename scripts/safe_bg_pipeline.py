#!/usr/bin/env python3
"""Safe background removal: edge-connected flood-fill only. NEVER paints outline strokes.

Detect bg from corner median (black or white). BFS from borders through near-bg
pixels → alpha 0. Interior (incl. black outlines/eyes) stays fully opaque.
Optional 1px alpha feather on outer edge. Crop + scale to TARGET_H.
Mr Black uses accent-seeded keep-region so black body is preserved.
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


def edge_flood_knock(
    im: Image.Image,
    *,
    tol: float | None = None,
    feather_px: int = 1,
) -> Image.Image:
    """Edge-connected flood-fill near-bg → transparent. Preserve interior darks."""
    arr = np.array(im.convert("RGBA"))
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3]
    a = arr[:, :, 3]
    bg = corner_median_rgb(arr)
    bg_lum = float(0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2])
    if tol is None:
        # black bg: tighter; white bg: slightly looser for JPG fringing
        tol = 38.0 if bg_lum < 80 else 42.0

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
    # also expand from existing holes
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

    # Optional 1px feather: only pixels adjacent to knocked that were bg-adjacent AA
    if feather_px > 0:
        a2 = out[:, :, 3]
        # soft fringe: near-transparent outer edge that is close to bg color
        fringe = np.zeros((h, w), dtype=bool)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                rolled = np.roll(np.roll(knock, dy, 0), dx, 1)
                fringe |= rolled
        fringe &= a2 > 0
        # only lighten alpha on near-bg fringe (anti-halo), never invent black
        close = near_bg(out[:, :, :3], bg, tol + 20)
        soft = fringe & close & (a2 < 250)
        # snap soft near-bg fringe fully transparent (no gray halo)
        out[soft, 3] = 0

    return Image.fromarray(out, "RGBA")


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

    # dilate keep slightly for AA
    keep = body.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            keep |= np.roll(np.roll(body, dy, 0), dx, 1)
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


def process_sprite(im: Image.Image, *, mode: str = "edge") -> Image.Image:
    if mode == "mrblack":
        cleared = prep_mrblack(im)
    else:
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
        print("usage: safe_bg_pipeline.py SRC DEST [edge|mrblack]")
        raise SystemExit(2)
    mode = sys.argv[3] if len(sys.argv) > 3 else "edge"
    img = process_file(Path(sys.argv[1]), Path(sys.argv[2]), mode=mode)
    print(f"wrote {sys.argv[2]} {img.size} mode={mode}")

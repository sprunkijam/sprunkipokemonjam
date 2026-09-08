#!/usr/bin/env python3
"""Light-gray keep-mask for Mr. Fun Computer (Phase 1/2)."""
from __future__ import annotations

from collections import deque

import numpy as np
from PIL import Image

from safe_bg_pipeline import (
    CHROMA_KEEP,
    DILATE_ITERS,
    GROW_ALPHA,
    MAX_CHANNEL_KEEP,
    SEED_ALPHA,
    _dilate_bool,
    corner_median_rgb,
    crop_and_scale,
    near_bg,
)


def keep_mask_light_gray(
    im: Image.Image,
    *,
    knock_floor_puddle: bool = False,
    dilate_iters: int = DILATE_ITERS,
    bg_tol: float = 28.0,
) -> Image.Image:
    """KEEP-mask for light-gray bg; grow through non-bg incl. black outlines/sludge.

    Soft gray ground shadow is near-bg → not grown into → knocked.
    If knock_floor_puddle: remove wide floor tar pool; keep narrow body-attached drips.
    """
    arr = np.array(im.convert("RGBA"))
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3].astype(np.int16)
    a = arr[:, :, 3]
    bg = corner_median_rgb(arr)
    is_near_bg = near_bg(arr[:, :, :3], bg, bg_tol) & (a > 0)

    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    ch = mx - mn

    seeds = (
        ((ch > CHROMA_KEEP) & (mx > 30) & (a > SEED_ALPHA) & ~is_near_bg)
        | ((mx > MAX_CHANNEL_KEEP) & (a > SEED_ALPHA) & ~is_near_bg)
        | (
            (rgb[:, :, 0] > 140)
            & (rgb[:, :, 1] > 120)
            & (rgb[:, :, 2] > 90)
            & (ch < 80)
            & (mx > 150)
            & (a > SEED_ALPHA)
            & ~is_near_bg
        )
        | (
            (rgb[:, :, 1] > 100)
            & (rgb[:, :, 1] > rgb[:, :, 0] + 20)
            & (rgb[:, :, 1] > rgb[:, :, 2] + 20)
            & (a > SEED_ALPHA)
            & ~is_near_bg
        )
    )

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
                if a[ny, nx] > GROW_ALPHA and not is_near_bg[ny, nx]:
                    keep[ny, nx] = True
                    q.append((ny, nx))

    if dilate_iters > 0:
        keep = _dilate_bool(keep, dilate_iters)
        keep &= a > 0

    out = arr.copy()
    out[~keep, 3] = 0

    if knock_floor_puddle:
        out_a = out[:, :, 3]
        out_mx = out[:, :, :3].max(axis=2)
        out_ch = out[:, :, :3].max(axis=2) - out[:, :, :3].min(axis=2)
        chromatic = (out_a > 0) & (out_mx > 50) & ((out_ch > 18) | (out_mx > 90))
        dark = (out_mx <= 70) & (out_a > 0) & ~chromatic
        rows = np.where(chromatic.any(axis=1))[0]
        feet_y = int(rows.max()) if len(rows) else h * 3 // 4

        narrow = np.zeros((h, w), dtype=bool)
        wide = np.zeros((h, w), dtype=bool)
        for y in range(h):
            row = dark[y]
            x = 0
            while x < w:
                if not row[x]:
                    x += 1
                    continue
                x1 = x
                while x1 < w and row[x1]:
                    x1 += 1
                if x1 - x >= 36:
                    wide[y, x:x1] = True
                else:
                    narrow[y, x:x1] = True
                x = x1

        torso_ymax = max(0, feet_y - 90)
        torso = chromatic & (np.arange(h)[:, None] < torso_ymax)
        protect = np.zeros((h, w), dtype=bool)
        q3: deque[tuple[int, int]] = deque()
        ys, xs = np.where(torso)
        for y, x in zip(ys.tolist(), xs.tolist()):
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and narrow[ny, nx] and not protect[ny, nx]:
                    protect[ny, nx] = True
                    q3.append((ny, nx))
        while q3:
            y, x = q3.popleft()
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and not protect[ny, nx] and narrow[ny, nx]:
                    protect[ny, nx] = True
                    q3.append((ny, nx))

        foot_ooze = (
            dark
            & _dilate_bool(chromatic & (np.arange(h)[:, None] >= feet_y - 60), 2)
            & (np.arange(h)[:, None] <= feet_y)
        )
        band = (np.arange(h)[:, None] >= feet_y - 100) & (np.arange(h)[:, None] <= feet_y + 2)
        chrom_dil = _dilate_bool(chromatic, 3)
        knock = wide & band
        knock |= dark & band & ~protect & ~foot_ooze & ~chrom_dil
        knock |= dark & (np.arange(h)[:, None] > feet_y)
        out[knock, 3] = 0

        body = np.zeros((h, w), dtype=bool)
        qb: deque[tuple[int, int]] = deque()
        ys, xs = np.where(chromatic & (out[:, :, 3] > 0))
        for y, x in zip(ys.tolist(), xs.tolist()):
            body[y, x] = True
            qb.append((y, x))
        while qb:
            y, x = qb.popleft()
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and not body[ny, nx] and out[ny, nx, 3] > GROW_ALPHA:
                    body[ny, nx] = True
                    qb.append((ny, nx))
        orphan = (out[:, :, 3] > 0) & ~body
        out[orphan, 3] = 0
        print(
            f"  puddle: feet_y={feet_y} knock={int(knock.sum())} "
            f"protect={int(protect.sum())} orphan={int(orphan.sum())}"
        )

    return Image.fromarray(out, "RGBA")


def process_mrfun(im: Image.Image, *, knock_floor_puddle: bool = False) -> Image.Image:
    return crop_and_scale(keep_mask_light_gray(im, knock_floor_puddle=knock_floor_puddle))

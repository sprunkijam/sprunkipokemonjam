#!/usr/bin/env python3
"""Aggressive transparent→content soft-fringe for character phase PNGs.

Only touches the exterior fringe (≈2–3 px into content). Preserves opaque
interiors and solid black outline strokes. Whitish chalk halos on the outer
edge are darkened toward local outline/neighbor color and/or alpha-reduced.

Usage:
  python3 scripts/soften_exterior_fringe.py
  python3 scripts/soften_exterior_fringe.py --dry-run
  python3 scripts/soften_exterior_fringe.py --checkers
  python3 scripts/soften_exterior_fringe.py --chars gray wenda mrfuncomputer
  python3 scripts/soften_exterior_fringe.py --wide --chars mrfuncomputer wenda
  python3 scripts/soften_exterior_fringe.py --band 10 --chars tunner --phases 1
  python3 scripts/soften_exterior_fringe.py --wide-white --band 30 --chars mrfuncomputer --phases 2
  python3 scripts/soften_exterior_fringe.py --black-ramp --black-band 10 --black-strength 0.7
  python3 scripts/soften_exterior_fringe.py --alpha-stops 10,30,70 --band 3
  python3 scripts/soften_exterior_fringe.py --alpha-stops 10,30,70 --band 3 --black-ramp --black-band 10 --black-strength 0.7
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "art"

# Skip non-character junk
SKIP_SUBSTRINGS = ("_backup", "_originals", "_preview", "intro-preview")

# Characters that need more aggressive whitish/hard-edge treatment
AGGRESSIVE_STEMS = frozenset({
    "gray", "wenda", "brud", "tunner", "mrfuncomputer", "simon", "clukr", "owakcx",
})

# Absolute alpha targets along distance into content (band depth).
# Outer (near transparent) → inner (near solid body).
DEFAULT_OUTER_ABS = 80   # ~31% of 255
DEFAULT_INNER_ABS = 210  # ~82% of 255
DEFAULT_BAND = 2.75

AGG_OUTER_ABS = 65       # ~25% of 255
AGG_INNER_ABS = 200      # ~78% of 255
AGG_BAND = 3.0

# Aggressive 3px exterior alpha cleanup: visibility 10% → 30% → 70% (outer→inward)
TRIPLE_STOP_PCTS = (10.0, 30.0, 70.0)  # percent visible
TRIPLE_STOP_BAND = 3.0

# Wide exterior fade (~20px) for worst hard-edge offenders
WIDE_BAND = 20.0
WIDE_OUTER_ABS = 40.0   # ~16% — soft ghost at the rim
WIDE_INNER_ABS = 255.0  # full by d=20
WIDE_OUTLINE_PROTECT_D = 12.0  # soften perimeter outlines; keep deep solid

# White-focused wide fade (Mr. Fun Computer casing / chalk)
WIDE_WHITE_BAND = 30.0
WIDE_WHITE_OUTER_ABS = 28.0   # ~11% — very soft white rim
WIDE_WHITE_INNER_ABS = 255.0
WIDE_WHITE_COLOR_BAND = 8.0   # gentler/shorter fade for saturated body
WIDE_WHITE_COLOR_OUTER = 70.0
WIDE_WHITE_COLOR_INNER = 255.0
WIDE_WHITE_OUTLINE_PROTECT_D = 10.0
# Whitish / light beige monitor casing: high luminance, low saturation
WHITEISH_LUM_MIN = 185.0
WHITEISH_SAT_MAX = 0.28
WHITEISH_MIN_CH = 150  # min(R,G,B) for chalk/beige

# Black-ward outline ramp: fringe RGB → black near exterior, original at band
BLACK_RAMP_BAND = 20.0

OUTLINE_LUM = 60.0
OUTLINE_ALPHA_MIN = 180
OUTLINE_FORCE_ALPHA = 250

WHITISH_MIN = 195  # min(R,G,B) threshold for chalk halo


def exterior_mask(alpha: np.ndarray, thr: int = 1) -> np.ndarray:
    """Flood exterior from image border through near-transparent pixels."""
    h, w = alpha.shape
    exterior = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()

    def seed(y: int, x: int) -> None:
        if alpha[y, x] < thr and not exterior[y, x]:
            exterior[y, x] = True
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
            if 0 <= ny < h and 0 <= nx < w and not exterior[ny, nx] and alpha[ny, nx] < thr:
                exterior[ny, nx] = True
                q.append((ny, nx))
    return exterior


def dist_to_true(mask: np.ndarray) -> np.ndarray:
    """Chamfer distance (approx Euclidean) to True cells."""
    h, w = mask.shape
    inf = float(h + w + 5)
    d = np.full((h, w), inf, dtype=np.float32)
    d[mask] = 0.0
    for y in range(h):
        for x in range(w):
            if x > 0:
                d[y, x] = min(d[y, x], d[y, x - 1] + 1)
            if y > 0:
                d[y, x] = min(d[y, x], d[y - 1, x] + 1)
            if x > 0 and y > 0:
                d[y, x] = min(d[y, x], d[y - 1, x - 1] + 1.414)
            if x + 1 < w and y > 0:
                d[y, x] = min(d[y, x], d[y - 1, x + 1] + 1.414)
    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            if x + 1 < w:
                d[y, x] = min(d[y, x], d[y, x + 1] + 1)
            if y + 1 < h:
                d[y, x] = min(d[y, x], d[y + 1, x] + 1)
            if x + 1 < w and y + 1 < h:
                d[y, x] = min(d[y, x], d[y + 1, x + 1] + 1.414)
            if x > 0 and y + 1 < h:
                d[y, x] = min(d[y, x], d[y + 1, x - 1] + 1.414)
    return d


def neighbor_any(mask: np.ndarray) -> np.ndarray:
    out = np.zeros_like(mask)
    out[:-1, :] |= mask[1:, :]
    out[1:, :] |= mask[:-1, :]
    out[:, :-1] |= mask[:, 1:]
    out[:, 1:] |= mask[:, :-1]
    return out


def metrics(arr: np.ndarray) -> dict[str, int | float | str]:
    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3]
    h, w = alpha.shape
    exterior = exterior_mask(alpha)
    next_e = neighbor_any(exterior)
    next2 = neighbor_any(next_e)
    opaque = alpha >= 250
    hard_edge = int((opaque & next_e).sum())
    nearly = int(((alpha >= 200) & (alpha < 250) & next_e).sum())
    soft_fringe = int(((alpha > 8) & (alpha < 250) & next_e).sum())
    whitish = int(
        (
            (rgb.min(axis=2) > WHITISH_MIN)
            & (alpha > 40)
            & (alpha < 250)
            & (next_e | next2)
        ).sum()
    )
    suggested = hard_edge + whitish + nearly
    # interior holes (a==0 not exterior) — must stay 0
    interior_holes = int(((alpha == 0) & ~exterior).sum())
    return {
        "size": f"{w}x{h}",
        "hard_edge_px": hard_edge,
        "nearly_hard_edge_px": nearly,
        "soft_fringe_px": soft_fringe,
        "whitish_fringe_px": whitish,
        "suggested_soften": suggested,
        "interior_holes": interior_holes,
    }


def local_dark_neighbor(rgb: np.ndarray, alpha: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """For masked pixels, average darker opaque neighbors (not whitish)."""
    h, w = alpha.shape
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    mn = rgb.min(axis=2)
    good = (alpha >= 180) & (mn < WHITISH_MIN) & (lum < 200)
    acc = np.zeros((h, w, 3), dtype=np.float64)
    cnt = np.zeros((h, w), dtype=np.float64)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            src = np.roll(np.roll(good, dy, 0), dx, 1)
            # zero-out wrap artifacts on edges
            if dy > 0:
                src[:dy, :] = False
            if dy < 0:
                src[dy:, :] = False
            if dx > 0:
                src[:, :dx] = False
            if dx < 0:
                src[:, dx:] = False
            shifted = np.roll(np.roll(rgb.astype(np.float64), dy, 0), dx, 1)
            m = src & mask
            acc[m] += shifted[m]
            cnt[m] += 1
    out = rgb.astype(np.float64).copy()
    has = cnt > 0
    for c in range(3):
        out[has, c] = acc[has, c] / cnt[has]
    # fallback: pull toward black for remaining whitish fringe
    need = mask & ~has
    out[need] = out[need] * 0.35  # darken toward black
    return out


def smoothstep(t: np.ndarray) -> np.ndarray:
    """Hermite smoothstep on [0,1]."""
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def parse_alpha_stops(spec: str) -> tuple[float, ...]:
    """Parse '10,30,70' style percent-visible stops → absolute alpha 0..255."""
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    if len(parts) < 2:
        raise ValueError(f"Need >=2 alpha stops, got {spec!r}")
    pcts = tuple(float(p) for p in parts)
    for p in pcts:
        if not (0.0 <= p <= 100.0):
            raise ValueError(f"Alpha stop percent out of range 0..100: {p}")
    return tuple(p / 100.0 * 255.0 for p in pcts)


def triple_stop_target(d: np.ndarray, band: float, stops_abs: tuple[float, ...]) -> np.ndarray:
    """Piecewise alpha targets along exterior distance.

    Stops map across the band: first stop at d→0 (outer), last at d=band (inner).
    For 3 stops over band=3 this yields ~10% in d≈0–1, ~30% in d≈1–2, ~70% in d≈2–3
    when stops are 10,30,70 (anchors at d=0, band/2, band with plateaus per third).
    """
    n = len(stops_abs)
    if n < 2:
        raise ValueError("stops_abs needs >=2 values")
    # Anchor stops at equal intervals: 0, band/(n-1), ..., band
    # For n=3, band=3: anchors at 0, 1.5, 3 — but user wants zone plateaus at
    # integer px. Prefer anchors at 0,1,2,...,min(n-1,band) then hold to band.
    if n == 3 and abs(band - 3.0) < 1e-6:
        xs = np.array([0.0, 1.0, 2.0, band], dtype=np.float32)
        ys = np.array([stops_abs[0], stops_abs[1], stops_abs[2], stops_abs[2]], dtype=np.float32)
    else:
        xs = np.linspace(0.0, band, n).astype(np.float32)
        ys = np.array(stops_abs, dtype=np.float32)
    # Vectorized piecewise linear
    return np.interp(d.astype(np.float64), xs.astype(np.float64), ys.astype(np.float64)).astype(np.float32)


def is_whitish_pixel(rgb: np.ndarray, lum: np.ndarray) -> np.ndarray:
    """High-luminance low-saturation (white / chalk / light beige casing)."""
    mn = rgb.min(axis=2)
    mx = rgb.max(axis=2)
    sat = np.zeros_like(mn, dtype=np.float32)
    nz = mx > 1
    sat[nz] = (mx[nz] - mn[nz]) / mx[nz]
    return (
        (lum >= WHITEISH_LUM_MIN)
        & (sat <= WHITEISH_SAT_MAX)
        & (mn >= WHITEISH_MIN_CH)
    ) | ((mn > WHITISH_MIN) & (sat < 0.35))


def soften_image(
    im: Image.Image,
    *,
    aggressive: bool = False,
    wide: bool = False,
    wide_white: bool = False,
    band_override: float | None = None,
    outer_abs_override: float | None = None,
    inner_abs_override: float | None = None,
    alpha_stops: tuple[float, ...] | None = None,
) -> Image.Image:
    arr = np.array(im.convert("RGBA"))
    out = arr.astype(np.float32).copy()
    alpha = out[:, :, 3]
    rgb = out[:, :, :3]

    exterior = exterior_mask(arr[:, :, 3])
    d = dist_to_true(exterior)

    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    whitish = is_whitish_pixel(rgb, lum)

    if alpha_stops is not None:
        # Dedicated multi-stop exterior alpha ramp (e.g. 10/30/70 over ~3px)
        band = float(band_override) if band_override is not None else (
            TRIPLE_STOP_BAND if len(alpha_stops) == 3 else DEFAULT_BAND
        )
        outline_protect_d = 0.0
        fringe = (alpha > 0) & (d > 0) & (d <= band)
        target = triple_stop_target(d, band, alpha_stops)
        wide_like = False
    elif wide_white:
        # Dual-band: strong ~30px on white/near-white; milder on saturated body
        white_band = float(band_override) if band_override is not None else WIDE_WHITE_BAND
        color_band = WIDE_WHITE_COLOR_BAND
        band = max(white_band, color_band)
        outline_protect_d = WIDE_WHITE_OUTLINE_PROTECT_D
        # Per-pixel target bands
        t_w = smoothstep(d / max(white_band, 1e-6))
        t_c = smoothstep(d / max(color_band, 1e-6))
        target_w = WIDE_WHITE_OUTER_ABS + (WIDE_WHITE_INNER_ABS - WIDE_WHITE_OUTER_ABS) * t_w
        target_c = WIDE_WHITE_COLOR_OUTER + (WIDE_WHITE_COLOR_INNER - WIDE_WHITE_COLOR_OUTER) * t_c
        # Cosine multiplier — stronger pull-down on white rim
        cos_w = 0.5 - 0.5 * np.cos(np.pi * np.clip(d / white_band, 0.0, 1.0))
        cos_c = 0.5 - 0.5 * np.cos(np.pi * np.clip(d / color_band, 0.0, 1.0))
        mult_w = 0.12 + 0.88 * cos_w
        mult_c = 0.28 + 0.72 * cos_c
        target = np.where(whitish, np.minimum(target_w, alpha * mult_w),
                          np.minimum(target_c, alpha * mult_c))
        # White fringe extends to white_band; color only to color_band
        fringe = (alpha > 0) & (d > 0) & (
            ((whitish) & (d <= white_band)) | ((~whitish) & (d <= color_band))
        )
        wide_like = True
    elif wide:
        band = float(band_override) if band_override is not None else WIDE_BAND
        outer_abs = WIDE_OUTER_ABS
        inner_abs = WIDE_INNER_ABS
        outline_protect_d = WIDE_OUTLINE_PROTECT_D
        fringe = (alpha > 0) & (d > 0) & (d <= band)
        t = smoothstep(d / max(band, 1e-6))
        target = outer_abs + (inner_abs - outer_abs) * t
        cos_t = 0.5 - 0.5 * np.cos(np.pi * np.clip(d / band, 0.0, 1.0))
        mult = 0.18 + 0.82 * cos_t
        target = np.minimum(target, alpha * mult)
        wide_like = True
    else:
        band = float(band_override) if band_override is not None else (
            AGG_BAND if aggressive else DEFAULT_BAND
        )
        outer_abs = float(
            outer_abs_override
            if outer_abs_override is not None
            else (AGG_OUTER_ABS if aggressive else DEFAULT_OUTER_ABS)
        )
        inner_abs = float(
            inner_abs_override
            if inner_abs_override is not None
            else (AGG_INNER_ABS if aggressive else DEFAULT_INNER_ABS)
        )
        # Narrow pass: protect black outline across the whole fringe
        outline_protect_d = 0.0
        fringe = (alpha > 0) & (d > 0) & (d <= band)
        t = smoothstep(d / max(band, 1e-6))
        target = outer_abs + (inner_abs - outer_abs) * t
        # Medium bands (>=6px): light cosine so already-soft pixels fade further
        if band >= 6.0:
            cos_t = 0.5 - 0.5 * np.cos(np.pi * np.clip(d / band, 0.0, 1.0))
            mult = 0.22 + 0.78 * cos_t
            target = np.minimum(target, alpha * mult)
            outline_protect_d = min(band * 0.55, 8.0)
        wide_like = band >= 6.0

    # Black outline: narrow mode protects all fringe outlines; wide/medium only
    # keeps deep interior outlines solid (d > outline_protect_d).
    black_outline = (
        (lum <= OUTLINE_LUM)
        & (alpha >= OUTLINE_ALPHA_MIN)
        & (d <= band + 2.0)
        & (d > outline_protect_d)
    )
    # Perimeter outline (wide/medium): allow fade with the band
    perimeter_outline = (
        wide_like
        & (lum <= OUTLINE_LUM)
        & (alpha >= OUTLINE_ALPHA_MIN)
        & (d > 0)
        & (d <= outline_protect_d)
    )

    apply = fringe & ~black_outline
    new_a = alpha.copy()
    # Only soften (never increase alpha); keep >=1 to avoid punching holes
    new_a[apply] = np.maximum(1.0, np.minimum(alpha[apply], target[apply]))

    # Whitish / light chalk halo on PARTIAL-alpha exterior fringe only
    # (never RGB-knock fully opaque white body fur — Wenda etc.)
    mn = rgb.min(axis=2)
    mx = rgb.max(axis=2)
    sat = np.zeros_like(mn)
    nz = mx > 1
    sat[nz] = (mx[nz] - mn[nz]) / mx[nz]
    chalk = (
        apply
        & (alpha > 8)
        & (alpha < 250)
        & (
            ((mn > WHITISH_MIN) & (alpha < 250))
            | ((lum > 170) & (sat < 0.22) & (mn > 140))
        )
    )
    # wide-white: also knock near-opaque white rim (casing) in the outer band
    if wide_white:
        chalk_opaque_rim = (
            apply
            & whitish
            & (alpha >= 250)
            & (d > 0)
            & (d <= min(band, 6.0))
        )
        chalk = chalk | chalk_opaque_rim
    if chalk.any():
        dark = local_dark_neighbor(arr[:, :, :3], arr[:, :, 3], chalk)
        blend = np.clip(1.0 - (d / max(band, 1e-6)), 0.55, 0.95)
        if wide_white:
            blend = np.where(whitish, np.clip(blend + 0.1, 0.65, 0.98), blend)
        for c in range(3):
            out[chalk, c] = (
                rgb[chalk, c] * (1.0 - blend[chalk])
                + dark[chalk, c] * blend[chalk]
            )
        chalk_scale = 0.32 if wide_white else (0.40 if (aggressive or wide_like) else 0.55)
        new_a[chalk] = np.maximum(
            1.0, np.minimum(new_a[chalk], target[chalk] * chalk_scale)
        )
        outer_lim = 3.0 if wide_white else (2.5 if wide_like else 1.25)
        outer_chalk = chalk & (d <= outer_lim)
        new_a[outer_chalk] = np.minimum(new_a[outer_chalk], 40.0 if wide_white else 45.0)

    # Force deep black outline solid (wide: only d > protect; narrow: all fringe)
    if black_outline.any():
        new_a[black_outline] = np.maximum(
            new_a[black_outline],
            np.maximum(alpha[black_outline], float(OUTLINE_FORCE_ALPHA)),
        )

    # Perimeter outline in wide mode already followed the fade via `apply`
    _ = perimeter_outline  # documented intent; covered by apply & ~black_outline

    out[:, :, 3] = new_a

    # Safety: never create interior holes
    result = np.clip(out, 0, 255).astype(np.uint8)
    ext2 = exterior_mask(result[:, :, 3])
    holes = (result[:, :, 3] == 0) & ~ext2
    if holes.any():
        result[holes] = arr[holes]

    return Image.fromarray(result, "RGBA")



def black_ramp_image(
    im: Image.Image,
    *,
    band: float = BLACK_RAMP_BAND,
    strength: float = 1.0,
) -> Image.Image:
    """Nudge exterior-fringe RGB toward black over `band` px; preserve alpha.

    t=1 at outer edge (d→0), t=0 at d=band (smoothstep).
    scale = 1.0 - strength * t  → strength=1.0 → 100% black at edge;
    strength=0.7 → keep 30% original RGB at edge (70% toward black).
    Only touches pixels with alpha>0 and 0 < d <= band (exterior distance).
    Interior body (d > band) unchanged — intentional glows stay.
    """
    arr = np.array(im.convert("RGBA"))
    out = arr.astype(np.float32).copy()
    alpha = out[:, :, 3]
    exterior = exterior_mask(arr[:, :, 3])
    d = dist_to_true(exterior)
    fringe = (alpha > 0) & (d > 0) & (d <= band)
    if not fringe.any():
        return im.convert("RGBA")
    # t=1 at outer edge → max black mix; t=0 at d=band → original
    t = 1.0 - smoothstep(d / max(band, 1e-6))
    strength = float(np.clip(strength, 0.0, 1.0))
    scale = 1.0 - strength * t  # multiply RGB toward 0 by up to `strength`
    for c in range(3):
        ch = out[:, :, c]
        ch[fringe] = ch[fringe] * scale[fringe]
        out[:, :, c] = ch
    result = np.clip(out, 0, 255).astype(np.uint8)
    ext2 = exterior_mask(result[:, :, 3])
    holes = (result[:, :, 3] == 0) & ~ext2
    if holes.any():
        result[holes] = arr[holes]
    return Image.fromarray(result, "RGBA")


def discover_phase_pngs(
    chars: list[str] | None = None,
    phases: list[int] | None = None,
) -> list[Path]:
    out: list[Path] = []
    for p in sorted(ART.glob("*-phase*.png")):
        name = p.name
        if any(s in name for s in SKIP_SUBSTRINGS):
            continue
        # only top-level art/, not nested
        if p.parent != ART:
            continue
        stem = name.rsplit("-phase", 1)[0]
        if chars is not None and stem not in chars:
            continue
        if phases is not None:
            try:
                ph = int(name.rsplit("-phase", 1)[1].split(".")[0])
            except ValueError:
                continue
            if ph not in phases:
                continue
        out.append(p)
    return out


def stem_of(path: Path) -> str:
    return path.name.rsplit("-phase", 1)[0]


def make_checker(img: Image.Image, cell: int = 16) -> Image.Image:
    ww, hh = img.size
    bg = Image.new("RGBA", (ww, hh))
    px = bg.load()
    for y in range(hh):
        for x in range(ww):
            c = 180 if ((x // cell) + (y // cell)) % 2 == 0 else 220
            px[x, y] = (c, c, c, 255)
    bg.alpha_composite(img)
    return bg


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Metrics only, no writes")
    ap.add_argument("--chars", nargs="*", default=None, help="Art stems to process")
    ap.add_argument(
        "--wide",
        action="store_true",
        help="~20px exterior alpha fade (worst offenders); allows perimeter outline soften",
    )
    ap.add_argument(
        "--wide-white",
        action="store_true",
        help="White/near-white focused fade (~30px) + milder color-body band",
    )
    ap.add_argument(
        "--band",
        type=float,
        default=None,
        help="Override exterior band depth in px (works with default/agg/wide/wide-white)",
    )
    ap.add_argument(
        "--phases",
        type=int,
        nargs="*",
        default=None,
        help="Only process these phase numbers (e.g. --phases 1)",
    )
    ap.add_argument(
        "--aggressive",
        action="store_true",
        help="Force AGG 2–3px params even for non-AGG stems",
    )
    ap.add_argument(
        "--alpha-stops",
        type=str,
        default=None,
        help="Comma percent-visible stops along exterior band, e.g. 10,30,70 "
             "(absolute alpha = pct/100*255). Implies soften for all selected files.",
    )
    ap.add_argument(
        "--outer-abs",
        type=float,
        default=None,
        help="Override outer (rim) absolute alpha target for two-stop ramp",
    )
    ap.add_argument(
        "--inner-abs",
        type=float,
        default=None,
        help="Override inner absolute alpha target for two-stop ramp",
    )
    ap.add_argument(
        "--black-ramp",
        action="store_true",
        help="Black-ward RGB ramp on exterior fringe (~20px); alone = ramp-only",
    )
    ap.add_argument(
        "--black-band",
        type=float,
        default=None,
        help="Black-ramp band depth in px (default 20)",
    )
    ap.add_argument(
        "--black-strength",
        type=float,
        default=1.0,
        help="Max mix toward black at outer edge (0..1; default 1.0 = 100%% black)",
    )
    ap.add_argument(
        "--checkers",
        action="store_true",
        help="Write /workspace/fringe-check-*.png for key sprites",
    )
    ap.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Optional CSV path for before/after metrics",
    )
    args = ap.parse_args()

    if args.wide and args.wide_white:
        print("Pick only one of --wide / --wide-white", file=sys.stderr)
        return 2

    files = discover_phase_pngs(args.chars, phases=args.phases)
    if not files:
        print("No phase PNGs found", file=sys.stderr)
        return 1

    rows: list[dict] = []
    print(
        f"{'file':32} {'hard':>5}->{'hard':<5} {'white':>5}->{'white':<5} "
        f"{'soft':>5}->{'soft':<5} {'sug':>5}->{'sug':<5} holes agg"
    )
    for path in files:
        stem = stem_of(path)
        aggressive = args.aggressive or (stem in AGGRESSIVE_STEMS)
        before_arr = np.array(Image.open(path).convert("RGBA"))
        before = metrics(before_arr)
        img = Image.fromarray(before_arr, "RGBA")
        stops = parse_alpha_stops(args.alpha_stops) if args.alpha_stops else None
        soften_flags = (
            args.wide or args.wide_white or args.band is not None or args.aggressive
            or args.alpha_stops is not None
            or args.outer_abs is not None or args.inner_abs is not None
        )
        # --black-ramp alone → ramp only; with soften flags → soften then ramp
        if args.black_ramp and not soften_flags:
            soft = black_ramp_image(
                img,
                band=float(args.black_band) if args.black_band is not None else BLACK_RAMP_BAND,
                strength=float(args.black_strength),
            )
            mode = 'BLK'
        else:
            soft = soften_image(
                img,
                aggressive=aggressive,
                wide=args.wide,
                wide_white=args.wide_white,
                band_override=args.band,
                outer_abs_override=args.outer_abs,
                inner_abs_override=args.inner_abs,
                alpha_stops=stops,
            )
            if args.black_ramp or args.black_band is not None:
                soft = black_ramp_image(
                    soft,
                    band=float(args.black_band) if args.black_band is not None else BLACK_RAMP_BAND,
                    strength=float(args.black_strength),
                )
            if stops is not None:
                mode = 'STP'
            elif args.wide_white:
                mode = 'WHT'
            elif args.wide:
                mode = 'WIDE'
            elif aggressive:
                mode = 'AGG'
            else:
                mode = '   '
            if args.band is not None:
                mode = f"{mode}@{args.band:g}"
            if stops is not None:
                pct = ",".join(f"{a/255*100:g}" for a in stops)
                mode = f"{mode}[{pct}]"
            if args.black_ramp or args.black_band is not None:
                bb = args.black_band if args.black_band is not None else BLACK_RAMP_BAND
                st = float(args.black_strength)
                suf = f"+BLK@{bb:g}x{st:g}" if st != 1.0 else f"+BLK@{bb:g}"
                mode = f"{mode}{suf}"
        after_arr = np.array(soft)
        after = metrics(after_arr)

        if after["interior_holes"] > before["interior_holes"]:
            print(f"ABORT {path.name}: interior holes increased "
                  f"{before['interior_holes']}→{after['interior_holes']}", file=sys.stderr)
            return 2

        if not args.dry_run:
            soft.save(path, "PNG")

        row = {
            "file": path.name,
            "stem": stem,
            "aggressive": aggressive,
            "before_hard_edge_px": before["hard_edge_px"],
            "after_hard_edge_px": after["hard_edge_px"],
            "before_whitish_fringe_px": before["whitish_fringe_px"],
            "after_whitish_fringe_px": after["whitish_fringe_px"],
            "before_soft_fringe_px": before["soft_fringe_px"],
            "after_soft_fringe_px": after["soft_fringe_px"],
            "before_suggested_soften": before["suggested_soften"],
            "after_suggested_soften": after["suggested_soften"],
            "before_interior_holes": before["interior_holes"],
            "after_interior_holes": after["interior_holes"],
            "size": before["size"],
        }
        rows.append(row)
        if mode == 'BLK':
            bb = args.black_band if args.black_band is not None else BLACK_RAMP_BAND
            st = float(args.black_strength)
            mode = f"BLK@{bb:g}x{st:g}" if st != 1.0 else f"BLK@{bb:g}"
        print(
            f"{path.name:32} {before['hard_edge_px']:5d}->{after['hard_edge_px']:<5d} "
            f"{before['whitish_fringe_px']:5d}->{after['whitish_fringe_px']:<5d} "
            f"{before['soft_fringe_px']:5d}->{after['soft_fringe_px']:<5d} "
            f"{before['suggested_soften']:5d}->{after['suggested_soften']:<5d} "
            f"{after['interior_holes']:5d} {mode}"
        )

    if args.checkers and not args.dry_run:
        if args.wide_white:
            check_map = {
                "mrfuncomputer-phase2.png": "/workspace/fringe-check-mrfuncomputer-p2-30px-white.png",
            }
        elif args.wide:
            check_map = {
                "mrfuncomputer-phase2.png": "/workspace/fringe-check-mrfuncomputer-p2-20px.png",
                "gray-phase2.png": "/workspace/fringe-check-gray-p2-20px.png",
                "wenda-phase2.png": "/workspace/fringe-check-wenda-p2-20px.png",
            }
        else:
            check_map = {
                "simon-phase1.png": "/workspace/fringe-check-simon-phase1.png",
                "gray-phase1.png": "/workspace/fringe-check-gray-phase1.png",
                "mrfuncomputer-phase2.png": "/workspace/fringe-check-mrfuncomputer-p2.png",
                "gray-phase2.png": "/workspace/fringe-check-gray-p2.png",
                "wenda-phase2.png": "/workspace/fringe-check-wenda-p2.png",
            }
        # Always emit Marty-requested key fringe checkers
        check_map = {
            "simon-phase1.png": "/workspace/fringe-check-simon-phase1.png",
            "gray-phase1.png": "/workspace/fringe-check-gray-phase1.png",
            **check_map,
        }
        for name, dest in check_map.items():
            p = ART / name
            if p.is_file():
                make_checker(Image.open(p).convert("RGBA")).save(dest)
                print(f"checker → {dest}")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"csv → {args.csv}")

    # summary
    bh = sum(r["before_hard_edge_px"] for r in rows)
    ah = sum(r["after_hard_edge_px"] for r in rows)
    bw = sum(r["before_whitish_fringe_px"] for r in rows)
    aw = sum(r["after_whitish_fringe_px"] for r in rows)
    bs = sum(r["before_suggested_soften"] for r in rows)
    a_s = sum(r["after_suggested_soften"] for r in rows)
    print(f"TOTAL hard {bh}→{ah}  whitish {bw}→{aw}  suggested {bs}→{a_s}  files={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Resample all WAV sound assets in sprunki-base.sb3 to 22050 Hz.

Uses ffmpeg when available (preferred). Updates project.json rate/sampleCount,
renames assets to new md5ext hashes, and drops orphaned old WAV files.
Preserves mono/stereo channel count (no upmix). Never prints secrets.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import wave
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SB3 = ROOT / "sprunki-base.sb3"
TARGET_RATE = 22050


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def wav_info(data: bytes) -> tuple[int, int, int]:
    """Return (nchannels, framerate, nframes) for a WAV blob."""
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getnchannels(), w.getframerate(), w.getnframes()


def resample_ffmpeg(data: bytes, channels: int, out_rate: int) -> bytes:
    """Resample WAV bytes with ffmpeg, preserving channel count."""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.wav"
        dst = Path(td) / "out.wav"
        src.write_bytes(data)
        # -ac keeps channel count; do not upmix
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-ar",
            str(out_rate),
            "-ac",
            str(channels),
            "-c:a",
            "pcm_s16le",
            str(dst),
        ]
        subprocess.check_call(cmd)
        return dst.read_bytes()


def resample_scipy(data: bytes, out_rate: int) -> bytes:
    """Fallback resample via scipy + wave (s16le)."""
    import numpy as np
    from scipy.signal import resample_poly

    with wave.open(io.BytesIO(data), "rb") as w:
        ch = w.getnchannels()
        rate = w.getframerate()
        sw = w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if sw != 2:
        raise RuntimeError(f"unsupported sample width {sw}")
    audio = np.frombuffer(frames, dtype=np.int16)
    if ch > 1:
        audio = audio.reshape(-1, ch)
    # rational resample 22050/48000 = 147/320
    from math import gcd

    g = gcd(out_rate, rate)
    up, down = out_rate // g, rate // g
    if audio.ndim == 1:
        out = resample_poly(audio.astype(np.float64), up, down)
        out = np.clip(np.rint(out), -32768, 32767).astype(np.int16)
    else:
        cols = []
        for c in range(ch):
            col = resample_poly(audio[:, c].astype(np.float64), up, down)
            cols.append(np.clip(np.rint(col), -32768, 32767).astype(np.int16))
        out = np.stack(cols, axis=1)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(out_rate)
        w.writeframes(out.tobytes())
    return buf.getvalue()


def md5ext_for(data: bytes, ext: str) -> str:
    return hashlib.md5(data).hexdigest() + "." + ext


def main() -> int:
    if not SB3.exists():
        print(f"missing {SB3}", file=sys.stderr)
        return 1

    use_ffmpeg = have_ffmpeg()
    print(f"resampler: {'ffmpeg' if use_ffmpeg else 'scipy'}")

    with zipfile.ZipFile(SB3, "r") as zin:
        namelist = zin.namelist()
        pj = json.loads(zin.read("project.json"))
        raw_assets = {n: zin.read(n) for n in namelist if n != "project.json"}

    # Collect unique WAV sound assets referenced by project.json
    sound_files: dict[str, list[tuple[dict, dict]]] = {}
    for target in pj.get("targets", []):
        for sound in target.get("sounds", []):
            md5 = sound.get("md5ext") or ""
            fmt = (sound.get("dataFormat") or sound.get("format") or "").lower()
            if not md5.endswith(".wav") and fmt != "wav":
                continue
            if not md5.endswith(".wav"):
                continue
            sound_files.setdefault(md5, []).append((target, sound))

    print(f"unique WAV assets: {len(sound_files)}")
    new_assets: dict[str, bytes] = {}
    rename: dict[str, str] = {}  # old md5ext -> new md5ext
    bytes_before = 0
    bytes_after = 0
    verified = 0

    for old_md5, refs in sorted(sound_files.items()):
        data = raw_assets.get(old_md5)
        if data is None:
            print(f"WARN missing asset {old_md5}", file=sys.stderr)
            continue
        bytes_before += len(data)
        try:
            ch, rate, nframes = wav_info(data)
        except wave.Error as e:
            print(f"WARN skip non-WAV {old_md5}: {e}", file=sys.stderr)
            new_assets[old_md5] = data
            bytes_after += len(data)
            continue

        old_dur = nframes / rate if rate else 0.0
        if rate == TARGET_RATE:
            new_data = data
            new_rate, new_frames = rate, nframes
        else:
            if use_ffmpeg:
                new_data = resample_ffmpeg(data, ch, TARGET_RATE)
            else:
                new_data = resample_scipy(data, TARGET_RATE)
            ch2, new_rate, new_frames = wav_info(new_data)
            if ch2 != ch:
                raise RuntimeError(f"channel count changed for {old_md5}: {ch}->{ch2}")

        new_dur = new_frames / new_rate if new_rate else 0.0
        if abs(new_dur - old_dur) > 0.05 and old_dur > 0:
            print(
                f"WARN duration drift {old_md5}: {old_dur:.3f}s -> {new_dur:.3f}s",
                file=sys.stderr,
            )

        new_md5 = md5ext_for(new_data, "wav")
        rename[old_md5] = new_md5
        new_assets[new_md5] = new_data
        bytes_after += len(new_data)

        for _target, sound in refs:
            sound["md5ext"] = new_md5
            sound["rate"] = int(new_rate)
            sound["sampleCount"] = int(new_frames)
            # Scratch assetId is md5 without extension
            sound["assetId"] = new_md5.rsplit(".", 1)[0]
            if "dataFormat" in sound:
                sound["dataFormat"] = "wav"
            if "format" in sound and sound["format"]:
                sound["format"] = ""

        if verified < 3:
            sc = refs[0][1]["sampleCount"]
            rt = refs[0][1]["rate"]
            print(
                f"verify {refs[0][1].get('name')}: "
                f"{old_dur:.3f}s @ {rate} -> {sc/rt:.3f}s @ {rt} "
                f"({len(data)} -> {len(new_data)} bytes, ch={ch})"
            )
            verified += 1

    # Keep non-WAV / non-replaced assets
    replaced = set(rename.keys())
    for name, data in raw_assets.items():
        if name in replaced:
            continue
        if name in new_assets:
            continue
        new_assets[name] = data

    # Orphan check: ensure every referenced md5ext exists
    missing = []
    for target in pj.get("targets", []):
        for sound in target.get("sounds", []):
            md5 = sound.get("md5ext")
            if md5 and md5 not in new_assets and md5 != "project.json":
                # costume/sound assets only
                if md5.endswith((".wav", ".mp3", ".png", ".svg")):
                    if md5 not in new_assets:
                        missing.append(md5)
        for costume in target.get("costumes", []):
            md5 = costume.get("md5ext")
            if md5 and md5 not in new_assets:
                missing.append(md5)
    if missing:
        print(f"ERROR missing refs after rewrite: {sorted(set(missing))[:10]}", file=sys.stderr)
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
        f"done: WAV {bytes_before} -> {bytes_after} bytes "
        f"(-{saved}, {pct:.1f}%), sb3 now {SB3.stat().st_size} bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

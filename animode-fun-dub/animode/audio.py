# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Sample-accurate slicing, pitch-preserving fitting, separation and muxing."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 24000


def run(args: list[str], timeout: int = 3600) -> str:
    """Execute without a shell; retain a bounded diagnostic on failure."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required executable missing: {args[0]}") from exc
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed: {result.stderr[-2500:]}")
    return result.stdout


def ffmpeg(*args: str) -> None:
    run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)])


def duration(path: Path) -> float:
    data = json.loads(
        run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    )
    if not any(s["codec_type"] == "video" for s in data["streams"]):
        raise ValueError("Input must contain a video stream.")
    value = float(data["format"]["duration"])
    if not math.isfinite(value) or not 0 < value <= 1800:
        raise ValueError("Use a video between 0 and 1800 seconds; split longer episodes.")
    return value


def normalize_file(source: Path, dest: Path, *, clean: bool = False) -> None:
    filters = "highpass=f=70,afftdn=nf=-30" if clean else "anull"
    ffmpeg("-i", str(source), "-vn", "-af", filters, "-ac", "1", "-ar", str(SR), str(dest))


def preprocess(video: Path, work: Path, device: str) -> tuple[Path, Path]:
    """Demucs lives in its own environment to avoid torch/torchaudio conflicts."""
    source = work / "source.wav"
    ffmpeg("-i", str(video), "-vn", "-ac", "2", "-ar", "44100", str(source))
    run(
        [
            os.environ.get("DEMUCS_PYTHON", sys.executable),
            "-m",
            "demucs",
            "--two-stems=vocals",
            "-n",
            "htdemucs",
            "-d",
            device,
            "-o",
            str(work / "stems"),
            str(source),
        ]
    )
    stem = work / "stems" / "htdemucs" / "source"
    vocals, background = work / "dialogue.wav", work / "background.wav"
    normalize_file(stem / "vocals.wav", vocals, clean=True)
    ffmpeg("-i", str(stem / "no_vocals.wav"), "-ac", "2", "-ar", str(SR), str(background))
    return vocals, background


def crop(source: Path, start: float, end: float, dest: Path) -> None:
    with sf.SoundFile(source) as f:
        left, right = round(start * f.samplerate), round(end * f.samplerate)
        if left < 0 or right <= left or right > len(f):
            raise ValueError(f"Invalid audio slice: {start:.6f}–{end:.6f}")
        f.seek(left)
        data = f.read(right - left, dtype="float32")
        sf.write(dest, data, f.samplerate, subtype="PCM_16")


def atempo_chain(rate: float) -> str:
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Tempo rate must be finite and positive.")
    stages = []
    while rate > 2:
        stages.append("atempo=2")
        rate /= 2
    while rate < 0.5:
        stages.append("atempo=0.5")
        rate /= 0.5
    stages.append(f"atempo={rate:.12f}")
    return ",".join(stages)


def fit_audio(source: Path, dest: Path, samples: int, *, force: bool = False) -> float:
    """Trim edge silence, protect the final phoneme and fit an exact sample budget."""
    data, sr = sf.read(source, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if not len(mono) or not np.isfinite(mono).all():
        raise ValueError("Fish Speech returned empty or invalid audio.")
    active = np.flatnonzero(np.abs(mono) > max(0.001, float(np.max(np.abs(mono))) * 0.01))
    if not len(active):
        raise ValueError("Fish Speech returned silence.")
    if samples < 1:
        raise ValueError("Timeline slot is empty.")
    margin = round(0.03 * sr)
    mono = mono[max(0, active[0] - margin) : min(len(mono), active[-1] + margin + 1)]
    # A protected tail absorbs small FFmpeg time-stretcher frame discrepancies.
    mono = np.pad(mono, (0, round(0.12 * sr)))
    rate = (len(mono) / sr) / (samples / SR)
    if not force and not 0.5 <= rate <= 2:
        raise ValueError(
            f"Required tempo {rate:.2f}x is outside 0.5–2x. "
            "Edit the Hindi line or explicitly allow extreme tempo."
        )
    prepared = dest.with_suffix(".prepared.wav")
    stretched = dest.with_suffix(".stretched.wav")
    sf.write(prepared, mono, sr, subtype="FLOAT")
    try:
        ffmpeg(
            "-i",
            str(prepared),
            "-af",
            atempo_chain(rate),
            "-ar",
            str(SR),
            "-ac",
            "1",
            str(stretched),
        )
        fitted, _ = sf.read(stretched, dtype="float32")
        if len(fitted) > samples:
            tail = fitted[samples:]
            if np.max(np.abs(tail), initial=0) > 0.01:
                raise ValueError("Time fitting would cut audible speech; shorten the Hindi line.")
        fitted = np.pad(fitted[:samples], (0, max(0, samples - len(fitted))))
        fade = min(round(0.005 * SR), samples // 2)
        if fade:
            fitted[:fade] *= np.linspace(0, 1, fade)
            fitted[-fade:] *= np.linspace(1, 0, fade)
        sf.write(dest, fitted, SR, subtype="PCM_16")
    finally:
        prepared.unlink(missing_ok=True)
        stretched.unlink(missing_ok=True)
    return rate


def mix_audio(
    clips: list[tuple[int, int, Path]],
    background: Path | None,
    total_samples: int,
    dest: Path,
    background_gain: float = 0.35,
) -> None:
    """Blockwise stereo mixing: bounded memory and no speech outside its slot."""
    if not 0 <= background_gain <= 1:
        raise ValueError("Background gain must be between zero and one.")
    previous_end = 0
    for left, right, path in sorted(clips):
        if not 0 <= left < right <= total_samples or left < previous_end:
            raise ValueError("Overlapping or invalid output slots.")
        info = sf.info(path)
        if info.samplerate != SR or info.frames != right - left or info.channels != 1:
            raise ValueError("Fitted audio does not match its slot.")
        previous_end = right
    bg = sf.SoundFile(background) if background else None
    try:
        if bg and (bg.samplerate != SR or bg.channels != 2):
            raise ValueError("Background must be stereo at the output sample rate.")
        with sf.SoundFile(dest, "w", samplerate=SR, channels=2, subtype="PCM_16") as out:
            for offset in range(0, total_samples, SR * 10):
                count = min(SR * 10, total_samples - offset)
                block = np.zeros((count, 2), dtype=np.float32)
                if bg:
                    bed = bg.read(count, dtype="float32", always_2d=True)
                    block[: len(bed)] = bed * background_gain
                for left, right, path in clips:
                    lo, hi = max(left, offset), min(right, offset + count)
                    if lo < hi:
                        with sf.SoundFile(path) as speech:
                            speech.seek(lo - left)
                            chunk = speech.read(hi - lo, dtype="float32")
                        block[lo - offset : hi - offset] += chunk[:, None] * 0.85
                # Soft limiting avoids hard digital clipping when stems peak together.
                over = np.abs(block) > 0.95
                block[over] = np.sign(block[over]) * (
                    0.95 + 0.05 * np.tanh((np.abs(block[over]) - 0.95) / 0.05)
                )
                out.write(block)
    finally:
        if bg:
            bg.close()


def mux(video: Path, audio: Path, output: Path, seconds: float) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + ".partial.mp4")
    try:
        ffmpeg(
            "-i",
            str(video),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            str(seconds),
            "-metadata:s:a:0",
            "language=hin",
            "-movflags",
            "+faststart",
            str(temporary),
        )
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)

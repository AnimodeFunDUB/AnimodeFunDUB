# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Mix mastering and audio/stem handoff bundles."""

from __future__ import annotations

import json
import math
import subprocess
import zipfile
from pathlib import Path

from .audio import SR, ffmpeg, mix_audio
from .editor import export_dialogue


def master_audio(source: Path, output: Path, target_lufs: float = -16) -> dict:
    """Two-pass EBU R128 normalization; 48 kHz/24-bit stereo deliverable."""
    if not -24 <= target_lufs <= -12:
        raise ValueError("Master loudness must be between -24 and -12 LUFS.")
    base = f"loudnorm=I={target_lufs}:TP=-1:LRA=11"
    analysis = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-i",
            str(source),
            "-af",
            base + ":print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if analysis.returncode:
        raise RuntimeError(f"Loudness analysis failed: {analysis.stderr[-1500:]}")
    start, end = analysis.stderr.rfind("{"), analysis.stderr.rfind("}")
    measurement = json.loads(analysis.stderr[start : end + 1])
    fields = {
        "measured_I": "input_i",
        "measured_LRA": "input_lra",
        "measured_TP": "input_tp",
        "measured_thresh": "input_thresh",
        "offset": "target_offset",
    }
    values = {key: float(measurement[value]) for key, value in fields.items()}
    if not all(math.isfinite(v) for v in values.values()):
        raise ValueError("Cannot master a silent or unmeasurable mix.")
    settings = base + ":linear=true:" + ":".join(f"{k}={v}" for k, v in values.items())
    ffmpeg(
        "-i",
        str(source),
        "-af",
        settings,
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s24le",
        str(output),
    )
    return {
        "target_lufs": target_lufs,
        "true_peak_target_db": -1,
        "input": measurement,
        "note": "FFmpeg may use dynamic mode when linear normalization cannot meet constraints.",
    }


def make_bundle(
    job: dict, fitted: list[tuple[int, int, Path]], directory: Path, master: Path, timing: Path
) -> dict[str, str]:
    """Archive relative filenames only; no source video, credentials or absolute-path job JSON."""
    exports = export_dialogue(job, directory)
    speaker_paths = []
    for index, speaker in enumerate(job["profiles"]):
        selected = [
            clip
            for clip, segment in zip(fitted, job["segments"], strict=True)
            if segment["speaker"] == speaker
        ]
        if not selected:
            continue
        path = directory / f"character_{index:02d}.wav"
        mix_audio(selected, None, round(job["duration"] * SR), path)
        speaker_paths.append((path, speaker, job["profiles"][speaker]["name"]))
    credits = {
        "project": "Animode Fun DUB",
        "target_language": "Hindi",
        "tracks": [{"file": p.name, "speaker": s, "name": n} for p, s, n in speaker_paths],
    }
    mapping = directory / "tracks.json"
    mapping.write_text(json.dumps(credits, ensure_ascii=False, indent=2), encoding="utf-8")
    bundle = directory / "studio_exports.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in [
            master,
            timing,
            mapping,
            *map(Path, exports.values()),
            *[p for p, _, _ in speaker_paths],
        ]:
            archive.write(path, path.name)
    return {**exports, "master": str(master), "bundle": str(bundle)}

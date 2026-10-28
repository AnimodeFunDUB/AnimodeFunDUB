# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Pyannote turns and overlap-safe reference selection."""

from __future__ import annotations

import math
from pathlib import Path


def diarize(
    audio: Path, device: str, token: str | None, speakers: int | None = None
) -> tuple[list[dict], list[dict]]:
    import soundfile as sf
    import torch
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1", token=token)
    pipeline.to(torch.device(device))
    wave, sr = sf.read(audio, dtype="float32", always_2d=True)
    result = pipeline(
        {"waveform": torch.from_numpy(wave.T.copy()), "sample_rate": sr},
        **({"num_speakers": speakers} if speakers else {}),
    )

    def rows(annotation):
        return sorted(
            [
                {"start": float(t.start), "end": float(t.end), "speaker": str(s)}
                for t, _, s in annotation.itertracks(yield_label=True)
            ],
            key=lambda t: (t["start"], t["end"]),
        )

    return rows(result.exclusive_speaker_diarization), rows(result.speaker_diarization)


def timeline(turns: list[dict], seconds: float, max_turn: float = 25) -> list[dict]:
    """Clip model boundary jitter; split long turns; never allocate overlapping slots."""
    output, previous = [], 0.0
    for row in sorted(turns, key=lambda x: x["start"]):
        if not all(math.isfinite(row[k]) for k in ("start", "end")):
            raise ValueError("Non-finite diarization timestamp.")
        start, end = max(previous, 0, row["start"]), min(seconds, row["end"])
        while end - start > 0.001:
            stop = min(end, start + max_turn)
            output.append(
                {"id": len(output), "speaker": row["speaker"], "start": start, "end": stop}
            )
            start = stop
        previous = max(previous, end)
    return output


def clean_intervals(speaker: str, regular: list[dict], seconds: float) -> list[tuple[float, float]]:
    """Subtract every other speaker from candidate reference spans."""
    candidates = []
    for row in regular:
        if row["speaker"] != speaker:
            continue
        pieces = [(max(0, row["start"]), min(seconds, row["end"]))]
        for other in regular:
            if other["speaker"] == speaker:
                continue
            remaining = []
            for start, end in pieces:
                if other["end"] <= start or other["start"] >= end:
                    remaining.append((start, end))
                else:
                    if start < other["start"]:
                        remaining.append((start, other["start"]))
                    if other["end"] < end:
                        remaining.append((other["end"], end))
            pieces = remaining
        candidates.extend((s + 0.05, e - 0.05) for s, e in pieces if e - s >= 2.1)
    return sorted(candidates, key=lambda p: p[1] - p[0], reverse=True)

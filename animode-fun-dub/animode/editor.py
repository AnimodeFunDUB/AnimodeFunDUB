# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Validated studio edits and portable dialogue exports."""

from __future__ import annotations

import copy
import csv
import io
import math
from pathlib import Path


def dialogue_rows(job: dict) -> list[list[str]]:
    return [
        [
            str(s["id"]),
            s["speaker"],
            f"{s['start']:.6f}",
            f"{s['end']:.6f}",
            s["source"],
            s["hindi"],
        ]
        for s in job["segments"]
    ]


def apply_edits(job: dict, rows: list[list]) -> dict:
    """Allow explicit speaker/time/text edits, without accepting paths or invented IDs."""
    from .pipeline import validate_job

    updated = copy.deepcopy(job)
    originals = {str(s["id"]): s for s in job["segments"]}
    if len(rows) != len(originals):
        raise ValueError("Keep the same segment rows; use existing IDs.")
    seen, segments = set(), []
    for row in rows:
        if len(row) != 6 or str(row[0]) not in originals or str(row[0]) in seen:
            raise ValueError("Invalid or duplicate segment ID.")
        identifier = str(row[0])
        seen.add(identifier)
        if row[1] not in job["profiles"]:
            raise ValueError(f"Unknown speaker: {row[1]}")
        start, end = float(row[2]), float(row[3])
        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError("Timestamps must be finite seconds.")
        if not isinstance(row[4], str) or not isinstance(row[5], str):
            raise ValueError("Source and Hindi dialogue must be text.")
        if len(row[4]) > 8000 or len(row[5]) > 8000:
            raise ValueError("A dialogue line exceeds 8000 characters; shorten it.")
        segment = copy.deepcopy(originals[identifier])
        segment.update(
            speaker=row[1], start=start, end=end, source=row[4].strip(), hindi=row[5].strip()
        )
        segments.append(segment)
    updated["segments"] = sorted(segments, key=lambda s: (s["start"], s["id"]))
    validate_job(updated)
    for key in ("exports", "last_output", "timing_report"):
        updated.pop(key, None)
    return updated


def timestamp(seconds: float, *, vtt: bool = False) -> str:
    value = round(seconds * 1000)
    hours, value = divmod(value, 3_600_000)
    minutes, value = divmod(value, 60_000)
    secs, millis = divmod(value, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{'.' if vtt else ','}{millis:03}"


def export_dialogue(job: dict, directory: Path) -> dict[str, str]:
    """Write UTF-8 subtitles and a spreadsheet-safe dialogue CSV."""
    directory.mkdir(parents=True, exist_ok=True)
    srt, vtt = [], ["WEBVTT\n"]
    table = io.StringIO(newline="")
    writer = csv.writer(table)
    writer.writerow(["id", "speaker", "character", "start", "end", "source", "hindi"])

    def safe_cell(value):
        text = str(value)
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text

    for index, segment in enumerate(job["segments"], start=1):
        text = " ".join(segment["hindi"].split()).replace("-->", "→")
        # WebVTT/SRT players may interpret tags. Preserve the spoken text, not markup.
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        srt.append(
            f"{index}\n{timestamp(segment['start'])} --> {timestamp(segment['end'])}\n{text}\n"
        )
        vtt.append(
            f"{index}\n{timestamp(segment['start'], vtt=True)} --> {timestamp(segment['end'], vtt=True)}\n{text}\n"
        )
        writer.writerow(
            [
                safe_cell(x)
                for x in [
                    segment["id"],
                    segment["speaker"],
                    job["profiles"][segment["speaker"]]["name"],
                    segment["start"],
                    segment["end"],
                    segment["source"],
                    segment["hindi"],
                ]
            ]
        )
    contents = {"srt": "\n".join(srt), "vtt": "\n".join(vtt), "csv": table.getvalue()}
    paths = {}
    for kind, content in contents.items():
        path = directory / f"hindi.{kind}"
        path.write_text(content, encoding="utf-8-sig" if kind == "csv" else "utf-8")
        paths[kind] = str(path)
    return paths

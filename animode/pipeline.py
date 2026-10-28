# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Two-phase Hindi dubbing: inspect/edit a job before rendering."""

from __future__ import annotations

import gc
import json
import logging
import os
import shutil
from pathlib import Path
from uuid import uuid4

import soundfile as sf

from . import audio
from .diarization import clean_intervals, diarize, timeline
from .fish import FishClient
from .models import LANGUAGES, HindiTranslator, Transcriber
from .state import atomic_json, commit_project, locked_project, tracked_render, write_status

log = logging.getLogger(__name__)


def release_models() -> None:
    import torch

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def save_job(job: dict) -> Path:
    path = Path(job["directory"]) / "job.json"
    atomic_json(path, job)
    return path


def validate_job(job: dict) -> None:
    if job.get("schema") != 1 or job.get("target_language") != "hi":
        raise ValueError("Expected an Animode Hindi job (schema 1).")
    total = round(job["duration"] * audio.SR)
    previous = 0
    seen = set()
    for row in job["segments"]:
        left, right = round(row["start"] * audio.SR), round(row["end"] * audio.SR)
        if not 0 <= left < right <= total or left < previous:
            raise ValueError(f"Invalid/overlapping timing in segment {row['id']}.")
        if not isinstance(row["id"], int) or row["id"] < 0 or row["id"] in seen:
            raise ValueError("Segment IDs must be unique non-negative integers.")
        seen.add(row["id"])
        if row["speaker"] not in job["profiles"]:
            raise ValueError("Unknown speaker in dialogue.")
        if not row["hindi"].strip():
            raise ValueError(f"Segment {row['id']} has no Hindi text.")
        previous = right
    if not seen:
        raise ValueError("No speech was transcribed; check separation and source language.")


class DubbingPipeline:
    def __init__(self, device: str = "cpu", asr_model: str = "large-v3"):
        if device not in {"cpu", "cuda"}:
            raise ValueError("Device must be cpu or cuda.")
        self.device, self.asr_model = device, asr_model

    def _analyze(
        self,
        video: str | Path,
        output_root: str | Path = "outputs",
        source_language: str = "ja",
        speakers: int | None = None,
        progress=None,
        work: Path | None = None,
    ) -> dict:
        if source_language not in LANGUAGES:
            raise ValueError(f"Source language must be one of {list(LANGUAGES)}.")
        if speakers is not None and not 1 <= speakers <= 32:
            raise ValueError("Speaker count must be 1–32, or omitted for automatic detection.")
        video = Path(video).resolve(strict=True)
        seconds = audio.duration(video)
        if work is None:
            work = Path(output_root).resolve() / uuid4().hex
            work.mkdir(parents=True)
        owned_video = work / ("source_video" + video.suffix.lower())
        shutil.copy2(video, owned_video)
        video = owned_video
        report = progress or (lambda value, message: log.info(message))
        report(0.05, "Separating dialogue and background")
        vocals, background = audio.preprocess(video, work, self.device)
        # Clamp to decoded audio length as well as video duration.
        speech_seconds = min(seconds, sf.info(vocals).duration)
        report(0.25, "Detecting speakers")
        exclusive, regular = diarize(vocals, self.device, os.environ.get("HF_TOKEN"), speakers)
        release_models()
        segments = timeline(exclusive, speech_seconds)
        if not segments:
            raise ValueError("No speakers detected. Check that the input contains audible speech.")
        profiles = {
            s: {"name": s, "style": "", "references": []}
            for s in sorted({row["speaker"] for row in segments})
        }
        report(0.4, "Transcribing individual speaker clips")
        asr = Transcriber(self.device, self.asr_model)
        clips = work / "segments"
        clips.mkdir()
        transcript = []
        warnings = []
        for row in segments:
            path = clips / f"{row['id']:06d}.wav"
            audio.crop(vocals, row["start"], row["end"], path)
            row["source"] = asr.transcribe(path, source_language)
            row["audio"] = str(path)
            if row["source"]:
                transcript.append(row)
            else:
                warnings.append(
                    f"Segment {row['id']}: no usable transcript; omitted from speech output."
                )
        refs = work / "references"
        refs.mkdir()
        for index, (speaker, profile) in enumerate(profiles.items()):
            budget = 30.0
            for start, end in clean_intervals(speaker, regular, speech_seconds):
                if budget < 2 or len(profile["references"]) == 3:
                    break
                end = min(end, start + 15, start + budget)
                path = refs / f"character_{index}_{len(profile['references'])}.wav"
                audio.crop(vocals, start, end, path)
                text = asr.transcribe(path, source_language)
                if text:
                    profile["references"].append(
                        {"audio": str(path), "text": text, "start": start, "end": end}
                    )
                    budget -= end - start
            if not profile["references"]:
                warnings.append(
                    f"{speaker}: no isolated reference >=2 seconds; assign custom reference audio."
                )
        del asr
        release_models()
        report(0.7, "Translating dialogue into Hindi")
        translator = HindiTranslator(source_language, self.device)
        for row in transcript:
            row["hindi"] = translator.translate(row["source"])
        del translator
        release_models()
        overlap = any(
            a["speaker"] != b["speaker"] and max(a["start"], b["start"]) < min(a["end"], b["end"])
            for i, a in enumerate(regular)
            for b in regular[i + 1 :]
        )
        if overlap:
            warnings.append(
                "Source contains simultaneous voices. Exclusive diarization allocates one voice "
                "per instant; secondary overlapping dialogue may be lost. Review the source."
            )
        job = {
            "schema": 1,
            "target_language": "hi",
            "source_language": source_language,
            "video": str(video),
            "duration": seconds,
            "directory": str(work),
            "background": str(background),
            "vocals": str(vocals),
            "profiles": profiles,
            "segments": transcript,
            "regular_turns": regular,
            "warnings": warnings,
            "source_has_overlap": overlap,
            "revision": 0,
        }
        if not transcript:
            raise ValueError(
                "No dialogue transcribed. Check the selected source language and vocals stem."
            )
        save_job(job)
        report(1, "Ready: review characters and Hindi dialogue")
        return job

    def analyze(
        self, video, output_root="outputs", source_language="ja", speakers=None, progress=None
    ):
        work = Path(output_root).resolve() / uuid4().hex
        work.mkdir(parents=True)

        def report(value, message):
            write_status(work, "analyzing", value, message)
            if progress:
                progress(value, message)

        try:
            job = self._analyze(video, output_root, source_language, speakers, report, work)
        except Exception as exc:
            write_status(work, "failed", 0, str(exc))
            raise
        write_status(work, "ready", 1, "Review characters and Hindi dialogue")
        return job

    @tracked_render
    def render(
        self,
        job: dict,
        output: str | Path | None = None,
        *,
        keep_background: bool = True,
        background_gain: float = 0.35,
        workers: int = 1,
        force_tempo: bool = False,
        accept_source_overlap: bool = False,
        master: bool = True,
        progress=None,
    ) -> Path:
        validate_job(job)
        if job.get("source_has_overlap") and not accept_source_overlap:
            raise ValueError(
                "Review simultaneous source voices first, then explicitly accept source overlap; "
                "secondary dialogue may be missing."
            )
        report = progress or (lambda value, message: log.info(message))
        for speaker in {s["speaker"] for s in job["segments"]}:
            if not job["profiles"][speaker]["references"]:
                raise ValueError(f"{speaker} needs a custom audio reference and transcript.")
        work = Path(job["directory"])
        output = Path(output).resolve() if output else work / "animode_hindi.mp4"
        if output.suffix.lower() != ".mp4" or output == Path(job["video"]).resolve():
            raise ValueError("Output must be a separate .mp4 file.")
        save_job(job)
        render_dir = work / ("render_" + uuid4().hex)
        report(0.1, "Batch synthesizing characters with Fish Speech")
        generated = FishClient().batch(
            job["segments"], job["profiles"], render_dir, workers, work / "tts_cache"
        )
        report(0.65, "Fitting each voice to its original timeline")
        fitted, timing = [], []
        for row, source in zip(job["segments"], generated, strict=True):
            left, right = round(row["start"] * audio.SR), round(row["end"] * audio.SR)
            target = render_dir / f"{row['id']:06d}.fitted.wav"
            try:
                rate = audio.fit_audio(source, target, right - left, force=force_tempo)
            except ValueError as exc:
                raise ValueError(f"Segment {row['id']} ({row['speaker']}): {exc}") from exc
            fitted.append((left, right, target))
            timing.append(
                {
                    "id": row["id"],
                    "speaker": row["speaker"],
                    "tempo": rate,
                    "start_sample": left,
                    "end_sample": right,
                }
            )
        report(0.85, "Mixing background and encoding Hindi video")
        mix = render_dir / "hindi_mix.wav"
        audio.mix_audio(
            fitted,
            Path(job["background"]) if keep_background else None,
            round(job["duration"] * audio.SR),
            mix,
            background_gain,
        )
        from .exports import make_bundle, master_audio

        mastered = render_dir / "hindi_master.wav"
        if master:
            mastering = master_audio(mix, mastered)
            atomic_json(render_dir / "mastering.json", mastering)
        else:
            shutil.copy2(mix, mastered)
        audio.mux(Path(job["video"]), mastered, output, job["duration"])
        report_path = render_dir / "timing.json"
        report_path.write_text(json.dumps(timing, indent=2), encoding="utf-8")
        job["exports"] = make_bundle(job, fitted, render_dir, mastered, report_path)
        job["last_output"], job["timing_report"] = str(output), str(report_path)
        save_job(job)
        report(1, "Hindi dub complete")
        return output

    @locked_project
    def preview_segment(
        self, job: dict, segment_id: int, *, regenerate: bool = False, force_tempo: bool = False
    ) -> Path:
        validate_job(job)
        segment = next((s for s in job["segments"] if s["id"] == segment_id), None)
        if segment is None:
            raise ValueError("Unknown dialogue segment.")
        if regenerate:
            segment["generation"] = uuid4().hex
            job["revision"] = job.get("revision", 0) + 1
            for key in ("exports", "last_output", "timing_report"):
                job.pop(key, None)
        directory = Path(job["directory"]) / "previews" / uuid4().hex
        directory.mkdir(parents=True)
        source = FishClient().batch(
            [segment], job["profiles"], directory, cache_dir=Path(job["directory"]) / "tts_cache"
        )[0]
        fitted = directory / "preview.wav"
        count = round(segment["end"] * audio.SR) - round(segment["start"] * audio.SR)
        audio.fit_audio(source, fitted, count, force=force_tempo)
        save_job(job)
        return fitted

    def dub_video(self, video_path: str | Path, **kwargs) -> Path:
        """Convenience path; use analyze/render for character or translation editing."""
        job = self.analyze(video_path, **kwargs)
        return self.render(job)


def set_reference(
    job: dict,
    speaker: str,
    reference: str | Path,
    transcript: str,
    name: str = "",
    style: str = "",
    *,
    persist: bool = True,
) -> None:
    """Copy a custom reference into the job, with its corresponding exact transcript."""
    if speaker not in job["profiles"] or not transcript.strip():
        raise ValueError("Select a detected character and provide the exact reference transcript.")
    target = Path(job["directory"]) / "references" / f"custom_{uuid4().hex}.wav"
    audio.normalize_file(Path(reference).resolve(strict=True), target, clean=True)
    if not 2 <= sf.info(target).duration <= 30:
        target.unlink(missing_ok=True)
        raise ValueError("Custom references must contain 2–30 seconds of one clean voice.")
    job["profiles"][speaker] = {
        "name": name.strip() or speaker,
        "style": style.strip(),
        "references": [{"audio": str(target), "text": transcript.strip()}],
    }
    if persist:
        for key in ("exports", "last_output", "timing_report"):
            job.pop(key, None)
        if (Path(job["directory"]) / "job.json").exists():
            commit_project(job, job.get("revision", 0))
        else:
            job["revision"] = job.get("revision", 0) + 1
            save_job(job)

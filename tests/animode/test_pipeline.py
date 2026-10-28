# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
import copy
import json

import numpy as np
import pytest
import soundfile as sf

from animode.audio import SR, ffmpeg
from animode.diarization import clean_intervals, timeline
from animode.pipeline import DubbingPipeline, set_reference, validate_job
from animode.webui import apply_dialogue


def job_fixture(tmp_path):
    for name in ("a.wav", "b.wav"):
        sf.write(tmp_path / name, np.ones(SR) * 0.1, SR)
    return {
        "schema": 1,
        "target_language": "hi",
        "source_language": "ja",
        "duration": 3,
        "directory": str(tmp_path),
        "video": str(tmp_path / "input.mp4"),
        "background": str(tmp_path / "background.wav"),
        "warnings": [],
        "profiles": {
            "A": {
                "name": "Hero",
                "references": [{"audio": str(tmp_path / "a.wav"), "text": "source A"}],
            },
            "B": {
                "name": "Rival",
                "references": [{"audio": str(tmp_path / "b.wav"), "text": "source B"}],
            },
        },
        "segments": [
            {"id": 0, "speaker": "A", "start": 0.0, "end": 1.0, "source": "a", "hindi": "नमस्ते"},
            {
                "id": 1,
                "speaker": "B",
                "start": 1.5,
                "end": 2.5,
                "source": "b",
                "hindi": "तुम कैसे हो?",
            },
        ],
    }


def test_reference_excludes_all_other_speakers():
    regular = [
        {"speaker": "A", "start": 0.0, "end": 10.0},
        {"speaker": "B", "start": 3.0, "end": 6.0},
    ]
    spans = clean_intervals("A", regular, 10)
    assert spans == [(6.05, 9.95), (0.05, 2.95)]
    assert all(e <= 3 or s >= 6 for s, e in spans)
    assert clean_intervals("B", regular, 10) == []


def test_timeline_clips_jitter_and_splits_long_turns():
    result = timeline(
        [
            {"speaker": "A", "start": -0.1, "end": 30.0},
            {"speaker": "B", "start": 29.999, "end": 40.0},
        ],
        35,
    )
    assert [(r["start"], r["end"]) for r in result] == [(0, 25), (25, 30), (30, 35)]


def test_editor_allows_explicit_speaker_edits_without_mutating_original(tmp_path):
    job = job_fixture(tmp_path)
    rows = [
        [str(s["id"]), s["speaker"], f"{s['start']:.3f}", f"{s['end']:.3f}", s["source"], "नई पंक्ति"]
        for s in job["segments"]
    ]
    updated = apply_dialogue(job, rows)
    assert updated["segments"][0]["hindi"] == "नई पंक्ति"
    assert job["segments"][0]["hindi"] == "नमस्ते"
    rows[0][1] = "B"
    reassigned = apply_dialogue(job, rows)
    assert reassigned["segments"][0]["speaker"] == "B"
    assert job["segments"][0]["speaker"] == "A"
    rows[0][0] = "unknown"
    with pytest.raises(ValueError, match="Invalid or duplicate"):
        apply_dialogue(job, rows)


def test_empty_dialogue_rejected(tmp_path):
    job = job_fixture(tmp_path)
    job["segments"][0]["hindi"] = " "
    with pytest.raises(ValueError, match="no Hindi"):
        validate_job(job)


def test_overlap_after_rounding_rejected(tmp_path):
    job = job_fixture(tmp_path)
    job["segments"][1]["start"] = 0.9
    with pytest.raises(ValueError, match="overlapping"):
        validate_job(job)


def test_custom_reference_is_copied_and_preserved(tmp_path):
    job = job_fixture(tmp_path)
    (tmp_path / "references").mkdir()
    ref = tmp_path / "custom.wav"
    sf.write(ref, 0.2 * np.sin(2 * np.pi * 220 * np.arange(3 * SR) / SR), SR)
    set_reference(job, "A", ref, "Exact sample words", "Hero", "confident")
    stored = job["profiles"]["A"]
    assert stored["name"] == "Hero" and stored["style"] == "confident"
    assert stored["references"][0]["audio"] != str(ref)
    assert json.loads((tmp_path / "job.json").read_text())["profiles"]["A"] == stored


def test_render_routes_distinct_profiles_and_writes_outputs(tmp_path, monkeypatch):
    job = job_fixture(tmp_path)
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=160x120:r=25:d=3", "-c:v", "libx264", job["video"])
    calls = []

    def synthesize(self, text, profile, output):
        calls.append((text, copy.deepcopy(profile)))
        wave = 0.15 * np.sin(2 * np.pi * 220 * np.arange(int(0.75 * SR)) / SR)
        sf.write(output, wave, SR)
        return output

    monkeypatch.setattr("animode.fish.FishClient.synthesize", synthesize)
    result = DubbingPipeline().render(job, keep_background=False, workers=2)
    assert result.exists()
    assert {p["name"] for _, p in calls} == {"Hero", "Rival"}
    assert next(p for text, p in calls if text == "नमस्ते")["references"][0]["audio"] == str(
        tmp_path / "a.wav"
    )
    assert next(p for text, p in calls if text != "नमस्ते")["references"][0]["audio"] == str(
        tmp_path / "b.wav"
    )
    timing = json.loads(open(job["timing_report"]).read())
    assert timing[0]["end_sample"] == SR
    assert timing[1]["start_sample"] == int(1.5 * SR)


def test_missing_reference_stops_before_network(tmp_path, monkeypatch):
    job = job_fixture(tmp_path)
    job["profiles"]["B"]["references"] = []
    monkeypatch.setattr(
        "animode.fish.FishClient.batch", lambda *a, **k: pytest.fail("Network called")
    )
    with pytest.raises(ValueError, match="B needs"):
        DubbingPipeline().render(job)


def test_analyze_builds_separate_references_and_hindi_job(tmp_path, monkeypatch):
    import animode.pipeline as module

    source = tmp_path / "anime.mp4"
    source.touch()
    vocals = tmp_path / "vocals.wav"
    background = tmp_path / "bg.wav"
    sf.write(vocals, 0.2 * np.sin(2 * np.pi * 220 * np.arange(7 * SR) / SR), SR)
    sf.write(background, np.zeros((7 * SR, 2)), SR)
    monkeypatch.setattr(module.audio, "duration", lambda _: 7.0)
    monkeypatch.setattr(module.audio, "preprocess", lambda *a: (vocals, background))
    turns = [{"start": 0.0, "end": 3.0, "speaker": "A"}, {"start": 4.0, "end": 7.0, "speaker": "B"}]
    monkeypatch.setattr(module, "diarize", lambda *a: (turns, turns))
    monkeypatch.setattr(module, "release_models", lambda: None)

    class ASR:
        def __init__(self, *a):
            pass

        def transcribe(self, path, language):
            assert language == "ja"
            return "source dialogue"

    class Translator:
        def __init__(self, *a):
            pass

        def translate(self, text):
            return "हिन्दी संवाद"

    monkeypatch.setattr(module, "Transcriber", ASR)
    monkeypatch.setattr(module, "HindiTranslator", Translator)
    job = module.DubbingPipeline().analyze(source, tmp_path / "jobs", "ja")
    validate_job(job)
    assert job["target_language"] == "hi"
    assert all(s["hindi"] == "हिन्दी संवाद" for s in job["segments"])
    a, b = job["profiles"]["A"]["references"][0], job["profiles"]["B"]["references"][0]
    assert a["audio"] != b["audio"]
    assert a["end"] < b["start"]
    assert sf.info(a["audio"]).duration == pytest.approx(2.9)

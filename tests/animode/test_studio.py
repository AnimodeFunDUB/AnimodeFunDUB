# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
import csv
import io
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from animode.audio import SR
from animode.editor import apply_edits, dialogue_rows, export_dialogue, timestamp
from animode.exports import master_audio
from animode.fish import FishClient
from animode.pipeline import DubbingPipeline
from animode.state import atomic_json
from animode.tasks import TaskQueue


def simple_job(tmp_path):
    return {
        "schema": 1,
        "target_language": "hi",
        "source_language": "ja",
        "duration": 3,
        "directory": str(tmp_path),
        "revision": 0,
        "warnings": [],
        "profiles": {"A": {"name": "Hero", "references": []}},
        "segments": [
            {"id": 0, "speaker": "A", "start": 0.1, "end": 1.0, "source": "Hello", "hindi": "नमस्ते"}
        ],
    }


@pytest.mark.parametrize("bad", ["nan", "inf", "-1", "4"])
def test_editor_rejects_invalid_start(tmp_path, bad):
    job = simple_job(tmp_path)
    rows = dialogue_rows(job)
    rows[0][2] = bad
    with pytest.raises(ValueError):
        apply_edits(job, rows)


def test_editor_does_not_accept_new_paths_or_speakers(tmp_path):
    job = simple_job(tmp_path)
    rows = dialogue_rows(job)
    rows[0][1] = "../../secret"
    with pytest.raises(ValueError, match="Unknown speaker"):
        apply_edits(job, rows)


def test_edits_invalidate_stale_export_links(tmp_path):
    job = simple_job(tmp_path)
    job["exports"] = {"master": "old.wav"}
    job["last_output"] = "old.mp4"
    result = apply_edits(job, dialogue_rows(job))
    assert "exports" not in result and "last_output" not in result


def test_subtitles_and_csv_are_hindi_and_safe(tmp_path):
    job = simple_job(tmp_path)
    job["profiles"]["A"]["name"] = '=HYPERLINK("evil")'
    paths = export_dialogue(job, tmp_path / "exports")
    srt = Path(paths["srt"]).read_text()
    assert "00:00:00,100 --> 00:00:01,000" in srt and "नमस्ते" in srt
    assert Path(paths["vtt"]).read_text().startswith("WEBVTT\n")
    rows = list(csv.reader(io.StringIO(Path(paths["csv"]).read_text(encoding="utf-8-sig"))))
    assert rows[1][2].startswith("'=HYPERLINK")
    assert rows[1][-1] == "नमस्ते"


def test_subtitle_rounding_carries_minutes():
    assert timestamp(59.9996) == "00:01:00,000"


def test_cache_reuses_and_invalidates_text_voice_and_model(tmp_path, monkeypatch):
    ref = tmp_path / "reference.wav"
    ref.write_bytes(b"reference-v1")
    profile = {"references": [{"audio": str(ref), "text": "source"}]}
    segment = {"id": 0, "hindi": "नमस्ते"}
    calls = []

    def synthesize(self, text, voice, path):
        calls.append(text)
        sf.write(path, np.ones(SR) * 0.1, SR)
        return path

    monkeypatch.setattr(FishClient, "synthesize", synthesize)
    client = FishClient()
    out = tmp_path / "out.wav"
    cache = tmp_path / "cache"
    client.cached_synthesize(segment, profile, out, cache)
    client.cached_synthesize(segment, profile, out, cache)
    assert len(calls) == 1
    segment["hindi"] = "हाँ"
    client.cached_synthesize(segment, profile, out, cache)
    ref.write_bytes(b"reference-v2")
    client.cached_synthesize(segment, profile, out, cache)
    monkeypatch.setenv("FISH_MODEL_ID", "different-checkpoint-revision")
    client.cached_synthesize(segment, profile, out, cache)
    segment["generation"] = "regenerate"
    client.cached_synthesize(segment, profile, out, cache)
    assert len(calls) == 5


def test_master_produces_48khz_24bit_stereo(tmp_path):
    source = tmp_path / "mix.wav"
    wave = 0.05 * np.sin(2 * np.pi * 220 * np.arange(4 * SR) / SR)
    sf.write(source, np.column_stack([wave, wave]), SR)
    output = tmp_path / "master.wav"
    report = master_audio(source, output)
    info = sf.info(output)
    assert info.samplerate == 48000 and info.channels == 2 and info.subtype == "PCM_24"
    assert info.duration == pytest.approx(4, abs=0.01)
    assert report["target_lufs"] == -16


def test_source_overlap_requires_review_before_tts(tmp_path, monkeypatch):
    job = simple_job(tmp_path)
    job["source_has_overlap"] = True
    monkeypatch.setattr(FishClient, "batch", lambda *a, **kw: pytest.fail("TTS should not run"))
    with pytest.raises(ValueError, match="simultaneous"):
        DubbingPipeline().render(job)
    assert json.loads((tmp_path / "status.json").read_text())["state"] == "failed"


def test_interrupted_jobs_are_not_silently_replayed(tmp_path):
    (tmp_path / "tasks").mkdir()
    task_id = "a" * 32
    atomic_json(tmp_path / "tasks" / f"{task_id}.json", {"id": task_id, "state": "running"})
    queue = TaskQueue(tmp_path)
    try:
        assert queue.read(task_id)["state"] == "interrupted"
    finally:
        queue.close()


def test_queue_rejects_invalid_actions_and_duplicate_project(tmp_path, monkeypatch):
    import threading

    finished = threading.Event()
    monkeypatch.setattr(TaskQueue, "_run", lambda *a: finished.wait(3))
    queue = TaskQueue(tmp_path, capacity=1)
    try:
        with pytest.raises(ValueError):
            queue.submit("shell")
        queue.submit("render", project_id="b" * 32)
        with pytest.raises(RuntimeError, match="already"):
            queue.submit("render", project_id="b" * 32)
        with pytest.raises(RuntimeError, match="full"):
            queue.submit("analyze", video="clip.mp4")
    finally:
        finished.set()
        queue.close()


def test_stale_studio_tab_cannot_overwrite_edit(tmp_path):
    import copy

    from animode.state import commit_project

    job = simple_job(tmp_path)
    atomic_json(tmp_path / "job.json", job)
    stale = copy.deepcopy(job)
    job["segments"][0]["hindi"] = "पहला बदलाव"
    commit_project(job, 0)
    stale["segments"][0]["hindi"] = "पुराना बदलाव"
    with pytest.raises(ValueError, match="another session"):
        commit_project(stale, 0)
    assert json.loads((tmp_path / "job.json").read_text())["segments"][0]["hindi"] == "पहला बदलाव"


def test_real_worker_records_invalid_media_failure_without_models(tmp_path):
    video = tmp_path / "broken.mp4"
    video.write_bytes(b"not a media file")
    queue = TaskQueue(tmp_path / "service")
    task_id = queue.submit("analyze", video=str(video), options={"source_language": "ja"})
    queue.close()  # Wait for the real subprocess, not a fake model server.
    task = queue.read(task_id)
    assert task["state"] == "failed"
    assert (queue.tasks / f"{task_id}.log").is_file()

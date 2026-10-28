# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
import json

import pytest
from fastapi.testclient import TestClient

from animode.api import create_app
from animode.state import atomic_json
from animode.tasks import TaskQueue

TOKEN = "test-only-token-with-at-least-24-characters"
HEADERS = {"Authorization": "Bearer " + TOKEN}
PROJECT = "c" * 32


@pytest.fixture
def studio(tmp_path, monkeypatch):
    directory = tmp_path / "projects" / PROJECT
    directory.mkdir(parents=True)
    job = {
        "schema": 1,
        "revision": 0,
        "target_language": "hi",
        "source_language": "ja",
        "duration": 3.0,
        "directory": str(directory),
        "warnings": [],
        "profiles": {"A": {"name": "Hero", "style": "", "references": []}},
        "segments": [
            {"id": 0, "speaker": "A", "start": 0.0, "end": 1.0, "source": "hello", "hindi": "नमस्ते"}
        ],
    }
    atomic_json(directory / "job.json", job)
    monkeypatch.setattr(TaskQueue, "_run", lambda *a: None)
    with TestClient(create_app(tmp_path, TOKEN)) as client:
        yield client, tmp_path


def test_api_requires_strong_configured_token(tmp_path):
    with pytest.raises(RuntimeError, match="ANIMODE_API_TOKEN"):
        create_app(tmp_path, "short")


def test_auth_and_health(studio):
    client, _ = studio
    assert client.get("/v1/health").status_code == 401
    assert client.get("/v1/health", headers=HEADERS).status_code == 200
    assert client.get("/v1/openapi.json", headers=HEADERS).status_code == 200


def test_project_response_hides_local_paths(studio):
    client, root = studio
    result = client.get(f"/v1/projects/{PROJECT}", headers=HEADERS)
    assert result.status_code == 200
    assert str(root) not in result.text
    assert result.json()["revision"] == 0


def test_api_edit_and_revision_conflict(studio):
    client, _ = studio
    payload = {"revision": 0, "rows": [["0", "A", "0.1", "1.2", "hello", "नया संवाद"]]}
    result = client.put(f"/v1/projects/{PROJECT}/dialogue", headers=HEADERS, json=payload)
    assert result.status_code == 200 and result.json()["revision"] == 1
    assert result.json()["segments"][0]["start"] == 0.1
    assert (
        client.put(f"/v1/projects/{PROJECT}/dialogue", headers=HEADERS, json=payload).status_code
        == 409
    )


def test_api_rejects_unknown_speakers(studio):
    client, _ = studio
    payload = {"revision": 0, "rows": [["0", "UNKNOWN", "0", "1", "hello", "नमस्ते"]]}
    assert (
        client.put(f"/v1/projects/{PROJECT}/dialogue", headers=HEADERS, json=payload).status_code
        == 422
    )


def test_task_submission_reserves_project_against_edits(studio):
    client, _ = studio
    response = client.post(f"/v1/projects/{PROJECT}/render", headers=HEADERS, json={"revision": 0})
    assert response.status_code == 202
    task = client.get("/v1/tasks/" + response.json()["task_id"], headers=HEADERS).json()
    assert task["state"] == "queued" and "root" not in task
    update = client.put(
        f"/v1/projects/{PROJECT}/voices/A", headers=HEADERS, json={"revision": 0, "name": "Renamed"}
    )
    assert update.status_code == 409


def test_api_rejects_empty_and_oversized_upload(studio):
    client, _ = studio
    assert client.post("/v1/projects", headers=HEADERS, content=b"").status_code == 400
    assert (
        client.post(
            "/v1/projects", headers={**HEADERS, "Content-Length": str(2 * 1024**3)}, content=b"x"
        ).status_code
        == 413
    )


def test_api_upload_stream_is_saved_with_server_generated_path(studio):
    client, root = studio
    response = client.post(
        "/v1/projects?extension=mp4&source_language=ja",
        headers=HEADERS,
        content=b"test-video-bytes",
    )
    assert response.status_code == 202
    task = json.loads((root / "tasks" / f"{response.json()['task_id']}.json").read_text())
    from pathlib import Path

    assert Path(task["video"]).read_bytes() == b"test-video-bytes"
    assert Path(task["video"]).name == "video.mp4"


def test_export_path_cannot_escape_project(studio):
    client, root = studio
    manifest = root / "projects" / PROJECT / "job.json"
    job = json.loads(manifest.read_text())
    private = root / "secret.txt"
    private.write_text("secret")
    job["exports"] = {"master": str(private)}
    atomic_json(manifest, job)
    response = client.get(f"/v1/projects/{PROJECT}/exports/master", headers=HEADERS)
    assert response.status_code == 404 and "secret" not in response.text


def test_api_rejects_non_uuid_ids(studio):
    client, _ = studio
    assert client.get("/v1/projects/not-a-project", headers=HEADERS).status_code == 404
    assert client.get("/v1/tasks/not-a-task", headers=HEADERS).status_code == 404

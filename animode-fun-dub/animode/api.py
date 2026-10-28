# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Authenticated single-operator studio API with isolated, bounded model workers."""

from __future__ import annotations

import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from filelock import FileLock, Timeout
from pydantic import BaseModel, Field

from .editor import apply_edits
from .pipeline import save_job
from .tasks import TaskQueue, identifier


class DialogueEdit(BaseModel):
    revision: int = Field(ge=0)
    rows: list[list[str]] = Field(min_length=1, max_length=20000)


class VoiceEdit(BaseModel):
    revision: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=120)
    style: str = Field(default="", max_length=200)


class RenderOptions(BaseModel):
    revision: int = Field(ge=0)
    keep_background: bool = True
    background_gain: float = Field(default=0.35, ge=0, le=1)
    workers: int = Field(default=1, ge=1, le=4)
    force_tempo: bool = False
    accept_source_overlap: bool = False
    master: bool = True


def create_app(root: Path | None = None, token: str | None = None) -> FastAPI:
    root = (root or Path(os.environ.get("ANIMODE_API_ROOT", "api_data"))).resolve()
    token = token or os.environ.get("ANIMODE_API_TOKEN", "")
    if len(token) < 24:
        raise RuntimeError("Set ANIMODE_API_TOKEN to a random secret of at least 24 characters.")

    @asynccontextmanager
    async def lifespan(app):
        app.state.queue = TaskQueue(root)
        try:
            yield
        finally:
            app.state.queue.close()

    def auth(authorization: Annotated[str | None, Header()] = None):
        if not authorization or not hmac.compare_digest(authorization, "Bearer " + token):
            raise HTTPException(
                401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"}
            )

    app = FastAPI(
        title="Animode Fun DUB Studio API",
        version="2.1.0",
        lifespan=lifespan,
        dependencies=[Depends(auth)],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def project(project_id):
        try:
            directory = root / "projects" / identifier(project_id)
            return json.loads((directory / "job.json").read_text())
        except (ValueError, FileNotFoundError):
            raise HTTPException(404, "Project not found") from None

    def public_job(job):
        return {
            "project_id": Path(job["directory"]).name,
            "revision": job.get("revision", 0),
            "duration": job["duration"],
            "source_language": job["source_language"],
            "target_language": "hi",
            "warnings": job["warnings"],
            "source_has_overlap": job.get("source_has_overlap", False),
            "profiles": {
                s: {
                    "name": p["name"],
                    "style": p.get("style", ""),
                    "references": len(p["references"]),
                }
                for s, p in job["profiles"].items()
            },
            "segments": [
                {k: s[k] for k in ("id", "speaker", "start", "end", "source", "hindi")}
                for s in job["segments"]
            ],
        }

    def mutable(project_id, revision):
        if project_id in app.state.queue.busy:
            raise HTTPException(409, "Project has queued or running work")
        job = project(project_id)
        if job.get("revision", 0) != revision:
            raise HTTPException(409, "Stale revision; fetch the project again")
        return job

    @app.get("/v1/health")
    def health():
        return {"status": "ok", "model_readiness": "Run python -m animode.preflight separately"}

    @app.get("/v1/openapi.json")
    def schema():
        return app.openapi()

    @app.post("/v1/projects", status_code=202)
    async def analyze(
        request: Request,
        source_language: Literal["ja", "en", "ko", "zh", "hi"] = "ja",
        extension: Literal["mp4", "mov", "mkv", "webm"] = "mp4",
        speakers: int = 0,
    ):
        if not 0 <= speakers <= 32:
            raise HTTPException(422, "Speaker count must be 0–32")
        maximum = 1024 * 1024 * 1024
        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length") from None
        if declared > maximum:
            raise HTTPException(413, "Video upload exceeds 1 GiB")
        directory = root / "uploads" / uuid4().hex
        directory.mkdir(parents=True)
        video = directory / f"video.{extension}"
        count = 0
        try:
            with video.open("wb") as output:
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > maximum:
                        raise HTTPException(413, "Video upload exceeds 1 GiB")
                    output.write(chunk)
            if not count:
                raise HTTPException(400, "Upload is empty")
            task_id = app.state.queue.submit(
                "analyze",
                video=str(video),
                options={"source_language": source_language, "speakers": speakers or None},
            )
        except Exception as exc:
            video.unlink(missing_ok=True)
            directory.rmdir()
            if isinstance(exc, RuntimeError):
                raise HTTPException(429, str(exc)) from exc
            raise
        return {"task_id": task_id}

    @app.get("/v1/tasks/{task_id}")
    def task(task_id: str):
        try:
            payload = app.state.queue.read(task_id)
        except (ValueError, FileNotFoundError):
            raise HTTPException(404, "Task not found") from None
        return {
            key: payload.get(key) for key in ("id", "state", "message", "progress", "project_id")
        }

    @app.get("/v1/projects/{project_id}")
    def get_project(project_id: str):
        return public_job(project(project_id))

    @app.put("/v1/projects/{project_id}/dialogue")
    def edit(project_id: str, edit: DialogueEdit):
        with app.state.queue.lock:
            job = mutable(project_id, edit.revision)
            try:
                with FileLock(str(Path(job["directory"]) / ".operation.lock"), timeout=0):
                    job = mutable(project_id, edit.revision)
                    updated = apply_edits(job, edit.rows)
                    updated["revision"] = job.get("revision", 0) + 1
                    save_job(updated)
            except Timeout:
                raise HTTPException(409, "Project is locked by another process") from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        return public_job(updated)

    @app.put("/v1/projects/{project_id}/voices/{speaker}")
    def voice(project_id: str, speaker: str, edit: VoiceEdit):
        if "[" in edit.style or "]" in edit.style:
            raise HTTPException(422, "Voice style must not contain brackets")
        with app.state.queue.lock:
            job = mutable(project_id, edit.revision)
            if speaker not in job["profiles"]:
                raise HTTPException(404, "Speaker not found")
            try:
                with FileLock(str(Path(job["directory"]) / ".operation.lock"), timeout=0):
                    job = mutable(project_id, edit.revision)
                    job["profiles"][speaker].update(name=edit.name, style=edit.style)
                    for key in ("exports", "last_output", "timing_report"):
                        job.pop(key, None)
                    job["revision"] = job.get("revision", 0) + 1
                    save_job(job)
            except Timeout:
                raise HTTPException(409, "Project is locked by another process") from None
        return public_job(job)

    @app.post("/v1/projects/{project_id}/render", status_code=202)
    def render(project_id: str, options: RenderOptions):
        with app.state.queue.lock:
            mutable(project_id, options.revision)
            try:
                task_id = app.state.queue.submit(
                    "render",
                    project_id=project_id,
                    options={
                        **options.model_dump(exclude={"revision"}),
                        "expected_revision": options.revision,
                    },
                )
            except RuntimeError as exc:
                raise HTTPException(429, str(exc)) from exc
        return {"task_id": task_id}

    @app.get("/v1/projects/{project_id}/exports/{kind}")
    def download(project_id: str, kind: Literal["video", "master", "srt", "vtt", "csv", "bundle"]):
        job = project(project_id)
        location = job.get("last_output") if kind == "video" else job.get("exports", {}).get(kind)
        if not location:
            raise HTTPException(404, "Export not available")
        path = Path(location).resolve()
        if (
            not path.is_relative_to((root / "projects" / project_id).resolve())
            or not path.is_file()
        ):
            raise HTTPException(404, "Export not available")
        return FileResponse(path, filename=path.name)

    return app


def main():
    import uvicorn
    from dotenv import load_dotenv

    load_dotenv()
    uvicorn.run(
        create_app(), host=os.environ.get("ANIMODE_API_HOST", "127.0.0.1"), port=8000, workers=1
    )


if __name__ == "__main__":
    main()

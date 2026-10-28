# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Atomic project status files and single-writer operations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from uuid import uuid4

from filelock import FileLock


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_status(work: Path, state: str, progress: float, message: str) -> None:
    atomic_json(
        work / "status.json",
        {
            "state": state,
            "progress": progress,
            "message": message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def tracked_render(function):
    @wraps(function)
    def wrapped(self, job, *args, **kwargs):
        work = Path(job["directory"])
        progress = kwargs.get("progress")

        def report(value, message):
            write_status(work, "rendering", value, message)
            if progress:
                progress(value, message)

        kwargs["progress"] = report
        with FileLock(str(work / ".operation.lock"), timeout=0):
            try:
                manifest = work / "job.json"
                if manifest.exists():
                    current = json.loads(manifest.read_text())
                    if current.get("revision", 0) != job.get("revision", 0):
                        raise ValueError("Project changed; reload before rendering.")
                result = function(self, job, *args, **kwargs)
            except Exception as exc:
                write_status(work, "failed", 0, str(exc))
                raise
            write_status(work, "complete", 1, "Hindi export ready")
            return result

    return wrapped


def commit_project(job: dict, expected_revision: int) -> Path:
    """Optimistic studio edit: reject stale tabs instead of overwriting another edit."""
    work = Path(job["directory"])
    path = work / "job.json"
    with FileLock(str(work / ".operation.lock"), timeout=0):
        current = json.loads(path.read_text())
        if current.get("revision", 0) != expected_revision:
            raise ValueError(
                "This project changed in another session. Resume it again before editing."
            )
        job["revision"] = expected_revision + 1
        atomic_json(path, job)
    return path


def locked_project(function):
    @wraps(function)
    def wrapped(self, job, *args, **kwargs):
        work = Path(job["directory"])
        with FileLock(str(work / ".operation.lock"), timeout=0):
            manifest = work / "job.json"
            if manifest.exists():
                current = json.loads(manifest.read_text())
                if current.get("revision", 0) != job.get("revision", 0):
                    raise ValueError("Project changed; reload before generating audio.")
            return function(self, job, *args, **kwargs)

    return wrapped

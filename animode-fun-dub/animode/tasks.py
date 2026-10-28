# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Bounded local task runner: one isolated model subprocess, durable task state."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from .state import atomic_json


def identifier(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError("Invalid ID.")
    return value


class TaskQueue:
    def __init__(self, root: Path, capacity: int = 8, timeout: int = 14400):
        self.root = root.resolve()
        self.tasks = self.root / "tasks"
        self.tasks.mkdir(parents=True, exist_ok=True)
        self.lease = FileLock(str(self.root / ".api.lock"), timeout=0)
        self.lease.acquire()
        self.lock = threading.RLock()
        self.busy: set[str] = set()
        self.slots = threading.BoundedSemaphore(capacity)
        self.timeout = timeout
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="animode-runner")
        for path in self.tasks.glob("*.json"):
            payload = json.loads(path.read_text())
            if payload["state"] in {"queued", "running"}:
                payload.update(
                    state="interrupted",
                    message="Service restarted. Inspect project and resubmit explicitly.",
                )
                atomic_json(path, payload)

    def read(self, task_id: str) -> dict:
        return json.loads((self.tasks / f"{identifier(task_id)}.json").read_text())

    def submit(
        self,
        action: str,
        *,
        video: str | None = None,
        project_id: str | None = None,
        options: dict | None = None,
    ) -> str:
        if action not in {"analyze", "render"}:
            raise ValueError("Unknown task action.")
        with self.lock:
            if project_id and project_id in self.busy:
                raise RuntimeError("This project already has queued or running work.")
            if not self.slots.acquire(blocking=False):
                raise RuntimeError("Task queue is full; retry after an existing task finishes.")
            task_id = uuid4().hex
            payload = {
                "id": task_id,
                "action": action,
                "state": "queued",
                "message": "Queued",
                "video": video,
                "project_id": project_id,
                "options": options or {},
                "root": str(self.root),
            }
            try:
                atomic_json(self.tasks / f"{task_id}.json", payload)
                if project_id:
                    self.busy.add(project_id)
                self.executor.submit(self._run, task_id)
            except Exception:
                self.busy.discard(project_id)
                self.slots.release()
                raise
            return task_id

    def _run(self, task_id: str):
        path = self.tasks / f"{task_id}.json"
        payload = self.read(task_id)
        project_id = payload.get("project_id")
        try:
            payload.update(state="running", message="Model worker started")
            atomic_json(path, payload)
            with (self.tasks / f"{task_id}.log").open("w") as log:
                process = subprocess.Popen(
                    [sys.executable, "-m", "animode.worker", str(path)],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=(os.name == "posix"),
                )
                try:
                    returncode = process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait()
                    raise
            current = self.read(task_id)
            if returncode or current["state"] not in {"complete", "failed"}:
                current.update(
                    state="failed", message="Worker stopped. Inspect the local task log."
                )
                atomic_json(path, current)
        except Exception:
            current = self.read(task_id)
            current.update(
                state="failed", message="Worker failed or exceeded its timeout. Inspect local logs."
            )
            atomic_json(path, current)
        finally:
            with self.lock:
                self.busy.discard(project_id)
                self.slots.release()

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=False)
        self.lease.release()

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Actionable setup diagnostics without downloading models or exposing secrets."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def check_environment(*, check_server: bool = True, device: str = "cpu") -> list[dict]:
    results = []

    def record(name, ok, detail):
        results.append({"check": name, "ok": bool(ok), "detail": detail})

    record("Python", sys.version_info >= (3, 11), sys.version.split()[0])
    for command in ("ffmpeg", "ffprobe"):
        record(
            command,
            bool(shutil.which(command)),
            "Available" if shutil.which(command) else "Install FFmpeg",
        )
    for name in (
        "soundfile",
        "numpy",
        "torch",
        "torchaudio",
        "faster_whisper",
        "transformers",
        "gradio",
        "ormsgpack",
    ):
        record(
            name,
            importlib.util.find_spec(name) is not None,
            f"Install requirements-animode.txt for {name}",
        )
    try:
        found = importlib.util.find_spec("pyannote.audio") is not None
    except ModuleNotFoundError:
        found = False
    record("pyannote.audio", found, "Community-1 requires pyannote.audio 4.x")
    record(
        "HF_TOKEN",
        bool(os.environ.get("HF_TOKEN")),
        "Required for initial gated model download; accept Community-1 conditions",
    )
    if device == "cuda":
        try:
            import torch

            record(
                "CUDA",
                torch.cuda.is_available(),
                "CUDA must be available to the app PyTorch environment",
            )
        except ImportError:
            record("CUDA", False, "Install matching CUDA PyTorch/torchaudio wheels")
    python = os.environ.get("DEMUCS_PYTHON", sys.executable)
    try:
        result = subprocess.run(
            [python, "-c", 'import demucs, torch, torchaudio; print("Demucs imports OK")'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        record(
            "Demucs environment",
            result.returncode == 0,
            "Available"
            if result.returncode == 0
            else "Set DEMUCS_PYTHON to a working separate Demucs environment",
        )
    except (OSError, subprocess.TimeoutExpired):
        record("Demucs environment", False, "DEMUCS_PYTHON executable missing or import timed out")
    root = Path(os.environ.get("ANIMODE_OUTPUT_ROOT", "outputs"))
    try:
        root.mkdir(parents=True, exist_ok=True)
        import tempfile

        with tempfile.TemporaryFile(dir=root):
            pass
        record("Output directory", True, "Writable")
    except OSError:
        record("Output directory", False, "Output directory is not writable")
    if check_server:
        import httpx

        from .fish import FishClient

        try:
            url = urlsplit(FishClient().url)
            health = urlunsplit((url.scheme, url.netloc, "/v1/health", "", ""))
            key = os.environ.get("FISH_API_KEY")
            response = httpx.get(
                health, headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=10
            )
            record(
                "Fish server",
                response.is_success,
                f"Health HTTP {response.status_code}; confirm S2-Pro checkpoint separately",
            )
        except Exception:
            record(
                "Fish server",
                False,
                "Cannot reach configured Fish server; inspect URL, authentication and health",
            )
    return results


def main():
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(description="Animode setup diagnostics")
    parser.add_argument("--offline", action="store_true", help="Do not contact Fish server")
    parser.add_argument(
        "--device", choices=["cpu", "cuda"], default=os.environ.get("ANIMODE_DEVICE", "cpu")
    )
    args = parser.parse_args()
    results = check_environment(check_server=not args.offline, device=args.device)
    print(json.dumps(results, indent=2))
    raise SystemExit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    main()

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
"""Fish Speech self-hosted /v1/tts MessagePack client with bounded batch dispatch."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import numpy as np
import soundfile as sf
from filelock import FileLock


class FishClient:
    def __init__(self, url: str | None = None):
        self.url = url or os.environ.get("FISH_TTS_URL", "http://127.0.0.1:8080/v1/tts")
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError(
                "FISH_TTS_URL must be an HTTP(S) endpoint without embedded credentials."
            )

    def synthesize(self, text: str, profile: dict, output: Path) -> Path:
        import httpx
        import ormsgpack

        references = [
            {"audio": Path(r["audio"]).read_bytes(), "text": r["text"]}
            for r in profile["references"]
        ]
        if not references or any(not r["text"].strip() for r in references):
            raise ValueError("Every character needs reference audio with its exact transcript.")
        prompt = profile.get("style", "").strip()
        if "[" in prompt or "]" in prompt or len(prompt) > 200:
            raise ValueError("Style must be at most 200 characters without brackets.")
        request = {
            "text": f"[{prompt}] {text}" if prompt else text,
            "references": references,
            "format": "wav",
            "streaming": False,
            "use_memory_cache": "on",
        }
        headers = {"Content-Type": "application/msgpack"}
        key = os.environ.get("FISH_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        # No automatic POST retries: an ambiguous timeout could duplicate costly generation.
        with httpx.Client(timeout=httpx.Timeout(300, connect=10), follow_redirects=False) as client:
            with client.stream(
                "POST",
                self.url,
                params={"format": "msgpack"},
                content=ormsgpack.packb(request),
                headers=headers,
            ) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 64 * 1024 * 1024:
                        raise ValueError("Fish response exceeds 64 MiB.")
                    chunks.append(chunk)
        audio, sr = sf.read(io.BytesIO(b"".join(chunks)), dtype="float32", always_2d=True)
        if not len(audio) or not np.isfinite(audio).all():
            raise ValueError("Invalid Fish Speech audio response.")
        sf.write(output, audio.mean(axis=1), sr, subtype="PCM_16")
        return output

    def cached_synthesize(
        self, segment: dict, profile: dict, output: Path, cache_dir: Path | None = None
    ) -> Path:
        if cache_dir is None:
            return self.synthesize(segment["hindi"], profile, output)
        # Cache identity covers text, voice audio bytes, transcript, style, endpoint,
        # model revision and user-requested regeneration. Credentials are never cached.
        references = [
            {"sha256": hashlib.sha256(Path(r["audio"]).read_bytes()).hexdigest(), "text": r["text"]}
            for r in profile["references"]
        ]
        identity = {
            "text": segment["hindi"],
            "style": profile.get("style", ""),
            "references": references,
            "endpoint": self.url,
            "model": os.environ.get("FISH_MODEL_ID", "s2-pro"),
            "generation": segment.get("generation", 0),
        }
        key = hashlib.sha256(
            json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = cache_dir / f"{key}.wav"
        with FileLock(str(cached.with_suffix(".lock")), timeout=360):
            valid = False
            if cached.exists():
                try:
                    info = sf.info(cached)
                    valid = info.frames > 0 and info.channels == 1
                except (RuntimeError, sf.LibsndfileError):
                    pass
            if not valid:
                temporary = cache_dir / f"{key}.{uuid4().hex}.wav"
                try:
                    self.synthesize(segment["hindi"], profile, temporary)
                    temporary.replace(cached)
                finally:
                    temporary.unlink(missing_ok=True)
            shutil.copy2(cached, output)
        return output

    def batch(
        self,
        segments: list[dict],
        profiles: dict,
        directory: Path,
        workers: int = 1,
        cache_dir: Path | None = None,
    ) -> list[Path]:
        if not 1 <= workers <= 4:
            raise ValueError("Fish workers must be between 1 and 4.")
        directory.mkdir(parents=True, exist_ok=True)

        def generate(segment):
            return self.cached_synthesize(
                segment,
                profiles[segment["speaker"]],
                directory / f"{segment['id']:06d}.wav",
                cache_dir,
            )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(generate, segments))

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
import io

import httpx
import numpy as np
import ormsgpack
import pytest
import soundfile as sf

from animode.fish import FishClient


def test_msgpack_contract_and_profile_isolation(tmp_path, monkeypatch):
    a, b = tmp_path / "A.wav", tmp_path / "B.wav"
    sf.write(a, np.ones(24000) * 0.1, 24000)
    sf.write(b, np.ones(24000) * 0.2, 24000)
    profiles = {
        "A": {"references": [{"audio": str(a), "text": "A source"}], "style": "calm"},
        "B": {"references": [{"audio": str(b), "text": "B source"}]},
    }
    seen = []

    def handle(request):
        assert request.headers["content-type"] == "application/msgpack"
        assert request.url.params["format"] == "msgpack"
        body = ormsgpack.unpackb(request.content)
        seen.append(body)
        buffer = io.BytesIO()
        sf.write(buffer, np.ones(24000) * 0.1, 24000, format="WAV")
        return httpx.Response(200, content=buffer.getvalue())

    client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs)
    )
    segments = [
        {"id": 0, "speaker": "A", "hindi": "नमस्ते"},
        {"id": 1, "speaker": "B", "hindi": "हाँ"},
    ]
    files = FishClient().batch(segments, profiles, tmp_path / "generated", 2)
    assert len(files) == 2 and all(p.exists() for p in files)
    by_text = {item["text"]: item for item in seen}
    assert by_text["[calm] नमस्ते"]["references"] == [{"audio": a.read_bytes(), "text": "A source"}]
    assert by_text["हाँ"]["references"] == [{"audio": b.read_bytes(), "text": "B source"}]


@pytest.mark.parametrize("status", [401, 429, 500])
def test_server_failure_not_retried(tmp_path, monkeypatch, status):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"example reference")
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, content=b"error")

    client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs)
    )
    with pytest.raises(httpx.HTTPStatusError):
        FishClient().synthesize(
            "नमस्ते", {"references": [{"audio": str(ref), "text": "hello"}]}, tmp_path / "out.wav"
        )
    assert len(calls) == 1 and not (tmp_path / "out.wav").exists()


def test_invalid_audio_response_fails(tmp_path, monkeypatch):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"reference")
    client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, content=b'{"error":"not audio"}')
            ),
            **kwargs,
        ),
    )
    with pytest.raises(sf.LibsndfileError):
        FishClient().synthesize(
            "नमस्ते", {"references": [{"audio": str(ref), "text": "hello"}]}, tmp_path / "out.wav"
        )
    assert not (tmp_path / "out.wav").exists()

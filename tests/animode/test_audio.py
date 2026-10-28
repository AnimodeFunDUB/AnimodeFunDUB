# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Animode Fun DUB
import json

import numpy as np
import pytest
import soundfile as sf

from animode.audio import SR, atempo_chain, crop, duration, ffmpeg, fit_audio, mix_audio, mux, run


def tone(path, seconds=1, sr=SR):
    wave = 0.2 * np.sin(2 * np.pi * 220 * np.arange(round(seconds * sr)) / sr)
    sf.write(path, wave, sr)
    return path


@pytest.mark.parametrize("seconds,target", [(1, 0.8), (1, 1.8), (2, 1.5)])
def test_fit_exact_duration_and_pitch(tmp_path, seconds, target):
    src, dest = tmp_path / "source.wav", tmp_path / "fitted.wav"
    tone(src, seconds)
    rate = fit_audio(src, dest, round(target * SR))
    data, sr = sf.read(dest)
    assert len(data) == round(target * SR)
    assert 0.5 <= rate <= 2
    spectrum = np.abs(np.fft.rfft(data))
    frequency = np.fft.rfftfreq(len(data), 1 / sr)[spectrum.argmax()]
    assert abs(frequency - 220) < 5


def test_extreme_tempo_requires_opt_in(tmp_path):
    src = tone(tmp_path / "src.wav", 2)
    with pytest.raises(ValueError, match="outside"):
        fit_audio(src, tmp_path / "out.wav", SR // 4)


def test_silence_is_rejected(tmp_path):
    src = tmp_path / "silent.wav"
    sf.write(src, np.zeros(SR), SR)
    with pytest.raises(ValueError, match="silence"):
        fit_audio(src, tmp_path / "out.wav", SR)


def test_crop_uses_samples(tmp_path):
    src = tone(tmp_path / "src.wav")
    dst = tmp_path / "slice.wav"
    crop(src, 0.123, 0.456, dst)
    original, _ = sf.read(src)
    actual, _ = sf.read(dst)
    np.testing.assert_array_equal(actual, original[round(0.123 * SR) : round(0.456 * SR)])


def test_gap_is_silent_and_no_spill(tmp_path):
    src = tone(tmp_path / "clip.wav", 0.5)
    dest = tmp_path / "mix.wav"
    mix_audio([(0, SR // 2, src), (SR, SR + SR // 2, src)], None, 2 * SR, dest)
    mix, _ = sf.read(dest)
    assert mix.shape == (2 * SR, 2)
    assert not np.any(mix[SR // 2 : SR])
    assert not np.any(mix[SR + SR // 2 :])
    assert np.max(np.abs(mix[: SR // 2])) > 0.1


def test_mixer_rejects_overlap(tmp_path):
    src = tone(tmp_path / "clip.wav")
    with pytest.raises(ValueError, match="Overlapping"):
        mix_audio([(0, SR, src), (SR // 2, SR + SR // 2, src)], None, 2 * SR, tmp_path / "out.wav")


def test_background_stereo_and_limiting(tmp_path):
    src = tone(tmp_path / "clip.wav")
    bg = tmp_path / "bg.wav"
    sf.write(bg, np.ones((SR, 2)) * 0.99, SR)
    mix_audio([(0, SR, src)], bg, SR, tmp_path / "mix.wav", 1)
    out, _ = sf.read(tmp_path / "mix.wav")
    assert np.isfinite(out).all() and np.max(np.abs(out)) < 1


@pytest.mark.parametrize("rate", [0.1, 0.5, 1, 2, 10])
def test_atempo_decomposition(rate):
    factors = [float(s.split("=")[1]) for s in atempo_chain(rate).split(",")]
    assert all(0.5 <= f <= 2 for f in factors)
    assert np.prod(factors) == pytest.approx(rate)


def test_mux_real_video_with_hindi_tag(tmp_path):
    video = tmp_path / "input.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=160x120:r=25:d=2", "-c:v", "libx264", str(video))
    speech = tone(tmp_path / "hindi.wav", 2)
    output = tmp_path / "dubbed.mp4"
    mux(video, speech, output, 2)
    assert duration(output) == pytest.approx(2, abs=0.06)
    streams = json.loads(
        run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)])
    )["streams"]
    assert next(s for s in streams if s["codec_type"] == "audio")["tags"]["language"] == "hin"

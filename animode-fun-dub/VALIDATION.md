# Validation — Studio 2.1

Checks performed on 2026-10-28 with Python 3.12 and the container's FFmpeg.

## Passed

- 54 targeted tests.
- Real FFmpeg PCM slicing, exact fitted duration, approximate pitch preservation,
  silence gaps, overlap rejection, stereo mixing and Hindi-tagged MP4 export.
- Real two-pass loudness mastering to a 48 kHz / 24-bit stereo WAV.
- Fake-model analysis and fake Fish synthesis with real fitting/mixing/muxing.
- MessagePack request contract, character-reference isolation and HTTP failure behavior.
- Generation-cache reuse and invalidation after text, reference, model or regeneration changes.
- SRT/VTT/CSV exports, including timestamp carry and CSV formula-leading cell escaping.
- Explicit speaker/script edits; invalid timestamps and unknown speakers rejected.
- Stale-tab revision protection; source-overlap review gate.
- API authentication, revisions, edit conflicts, upload bounds, path confinement and task submission.
- Interrupted-task recovery and queue limits.
- A real worker subprocess handles invalid media, saves failure state and writes its private log.
- Gradio localhost /config returned HTTP 200 with 60 components.
- Ruff, Python compilation and editable packaging checks.

One dependency deprecation warning originated in Starlette's test client; no tests failed.

## Not verified

No actual pyannote, Whisper, NLLB, Demucs or Fish Speech model inference was run.
No model weights, Hugging Face access token, live Fish service or GPU were provisioned.
The Docker image was not built; a provided Dockerfile/Compose recipe is not a deployed service.
The UI smoke test is server/config verification, not a human browser visual/usability review.
The MIT relicense, legacy-code removal and README refresh were checked by compilation and reference
searches only; the test suite was not re-run after those packaging changes.

## Real-model acceptance

1. Install the three isolated environments and run preflight.
2. Analyze 15–30 seconds of real two-character anime.
3. Check separated dialogue/music, speaker assignments and clean reference clips/transcripts.
4. Correct Hindi phrasing and estimated boundaries; review simultaneous source dialogue.
5. Preview both characters, regenerate a clip, then export the full video/master.
6. Listen for voice similarity, Hindi pronunciation, clipped endings, music bleed and artifacts.
7. Verify GPU memory, processing time, disk growth and installed dependency versions.
8. Freeze the accepted environment and review model licenses before deployment.

This delivery verifies orchestration and service controls, not ElevenLabs-level voice quality,
commercial clearance, perfect source separation, anime lip-sync or production uptime.

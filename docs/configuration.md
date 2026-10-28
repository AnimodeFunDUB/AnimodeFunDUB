# Configuration

Copy .env.example to .env and keep secrets out of git.

| Variable | Meaning |
|---|---|
| HF_TOKEN | Initial access to gated pyannote model files |
| DEMUCS_PYTHON | Absolute executable path of isolated separator environment |
| FISH_TTS_URL / FISH_API_KEY | Fish MessagePack endpoint and optional bearer secret |
| FISH_MODEL_ID | Cache checkpoint/revision identity; update when server weights change |
| ANIMODE_DEVICE | cpu/cuda for UI/API analysis |
| ASR_MODEL | faster-whisper model, default large-v3 |
| ANIMODE_OUTPUT_ROOT | UI projects, default outputs |
| ANIMODE_API_TOKEN | API secret, at least 24 characters |
| ANIMODE_API_ROOT | API data, default api_data |
| ANIMODE_UI_HOST / ANIMODE_API_HOST | Native defaults 127.0.0.1; container binds 0.0.0.0 |
| FISH_CONTAINER_TTS_URL | Compose's container-reachable Fish endpoint |
| GRADIO_ANALYTICS_ENABLED | Set False for local Studio |

CLI --device, --asr-model and --work-dir are explicit arguments, not the UI environment defaults.
Hindi is the fixed target. Schema-1 jobs gain optional revision, source_has_overlap, exports and
per-segment generation fields. Absolute paths support local resumes. Update them after moving
a project. Share the export ZIP rather than a private manifest.

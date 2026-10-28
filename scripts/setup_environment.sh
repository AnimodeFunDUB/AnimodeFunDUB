#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"
command -v ffmpeg >/dev/null || { echo "Install FFmpeg/ffprobe first."; exit 1; }
command -v python3.11 >/dev/null || { echo "Install Python 3.11 first."; exit 1; }
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[test]'
if [[ ! -f .env ]]; then cp .env.example .env; fi
echo "Configure separate Demucs and Fish environments using README."
echo "Then run: source .venv/bin/activate"
echo "Then run: python -m animode.preflight"

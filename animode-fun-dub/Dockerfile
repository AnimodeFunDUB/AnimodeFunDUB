FROM python:3.11-slim-bookworm
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ARG DEMUCS_TORCH_INDEX=https://download.pytorch.org/whl/cpu
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    GRADIO_ANALYTICS_ENABLED=False DEMUCS_PYTHON=/opt/demucs/bin/python \
    ANIMODE_UI_HOST=0.0.0.0 HF_HOME=/app/model_cache
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-animode.txt .
RUN python -m pip install --no-cache-dir --index-url ${TORCH_INDEX} torch==2.8.0 torchaudio==2.8.0 \
    && python -m pip install --no-cache-dir -r requirements-animode.txt
RUN python -m venv /opt/demucs \
    && /opt/demucs/bin/python -m pip install --no-cache-dir --index-url ${DEMUCS_TORCH_INDEX} torch==2.5.1 torchaudio==2.5.1 \
    && /opt/demucs/bin/python -m pip install --no-cache-dir 'numpy<2' demucs==4.0.1 soundfile
COPY . .
RUN python -m pip install --no-cache-dir --no-deps . \
    && useradd --uid 10001 --create-home animode \
    && mkdir -p /app/outputs /app/api_data /app/model_cache \
    && chown -R animode:animode /app
USER animode
EXPOSE 7860 8000
CMD ["python", "-m", "animode.webui"]

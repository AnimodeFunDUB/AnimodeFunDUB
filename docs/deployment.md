# Deployment

Linux/WSL2 is the baseline. Other platforms have not been validated with the complete model stack.
Use the main README for native setup, then run preflight and the UI or API.

## CPU Docker baseline

~~~bash
cp .env.example .env
# Configure HF_TOKEN and FISH_CONTAINER_TTS_URL.
docker compose up --build studio
# For API mode, also configure ANIMODE_API_TOKEN:
docker compose --profile api up --build api
~~~

The image has separate app/Demucs environments, a non-root user and persistent named volumes.
Fish Speech is a separately provisioned service. The sample container URL uses host.docker.internal;
a host-loopback-only Fish listener is not reachable that way. Configure a reachable authenticated
listener. Do not expose the Studio directly as an unauthenticated public multi-user app.

This Docker recipe was not built in the delivery environment. Verify dependency/model runtime
compatibility, download access, cache permissions and disk space on your host.

## CUDA

Default Docker/Compose uses CPU. Select matching wheel indexes through TORCH_INDEX and
DEMUCS_TORCH_INDEX, enable NVIDIA container access, and override ANIMODE_DEVICE=cuda.
Main Torch 2.8 and separator Torch 2.5.1 may need different wheel indexes. Fish has separate
hardware requirements. Run one heavy workload per GPU until memory capacity is measured.

## State and retention

- outputs/: UI/CLI projects, source copies, stems, reference clips, cache and renders.
- api_data/uploads/: API source uploads.
- api_data/projects/: API projects.
- api_data/tasks/: task states and private worker logs.
- model-cache Docker volume: downloaded models.

There is no automatic retention. Back up exports and delete only inactive/completed directories.
Intermediate files may consume many times the input size. Use separate UI/API project roots.
Do not edit a running project's files externally. Restarted tasks become interrupted;
failed analysis must be resubmitted, while completed analysis remains renderable.

For remote access, add a suitable authenticated TLS gateway. API tokens do not provide tenant
isolation. Multi-node operation needs a distributed queue, quotas, monitoring and recovery design.

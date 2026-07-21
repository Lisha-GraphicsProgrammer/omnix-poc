# OMNIX Deployment Guide

## Quick start — bring up the backend + database

```bash
docker compose up -d --build
```

This starts:
- **`postgres`** — PostgreSQL 16, data persisted in the `omnix_pg_data` volume
- **`api`** — the FastAPI backend (built from the `Dockerfile`), listening on `http://localhost:8000`

The API waits for Postgres to report healthy (via `depends_on: condition: service_healthy`) before starting, so there's no manual "wait for the DB" step.

First run will seed the database automatically (same `seed()` call that runs in local dev).

To stop everything:
```bash
docker compose down
```

To stop and wipe all data (Postgres + saved incident screenshots):
```bash
docker compose down -v
```

## What DOES containerize

- FastAPI backend (`api_server.py`)
- The detection pipeline (`run_pipeline.py`) — launched as a **subprocess of the API container** when a rule is applied (see "What does NOT containerize" below for the implications of this)
- PostgreSQL

## What does NOT containerize yet

### 1. Ollama (the local LLM used for rule generation)

`POST /api/rules/generate` calls out to `http://localhost:11434` (Ollama) to convert plain-English instructions into pipeline configs. Ollama is **not** part of this compose file, for two reasons:

- It needs a GPU-capable host to run at a usable speed. Bundling it into a generic `docker compose up` would either be unusably slow on CPU-only hosts, or require every deployment target to have GPU passthrough configured — not a safe default.
- It's most naturally run once per host (not per-project), since multiple OMNIX deployments on the same machine can share one Ollama instance.

**What you need to do:** run Ollama separately on the host (or on its own GPU-capable machine), then point the `api` container at it. The compose file's `OLLAMA_MODEL` env var controls which model name is requested, but the *URL* (`OLLAMA_URL` in `api_server.py`, currently hardcoded to `http://localhost:11434/api/generate`) will need to become configurable via an env var in a follow-up change — right now, `localhost` inside the `api` container refers to the container itself, not the host machine, so LLM rule generation will not reach a host-level Ollama install without either:
- Running Ollama in its own container on the same Docker network (recommended for a real deployment), or
- Passing `--add-host=host.docker.internal:host-gateway` (Linux) or using `host.docker.internal` directly (Mac/Windows) and updating `OLLAMA_URL` to use that hostname instead of `localhost`.

This is flagged as a known gap, not silently glossed over — LLM rule generation will not work out of the box against a host-installed Ollama until one of the above is wired in.

### 2. The `run_pipeline.py` subprocess model

Today, `apply_rule()` in `api_server.py` starts `run_pipeline.py` as a **subprocess of the API process itself** (`subprocess.Popen([sys.executable, "run_pipeline.py", ...])`). Inside the `api` container, this means:

- The pipeline process shares the API container's filesystem, Python environment, and lifecycle — if the `api` container restarts, the pipeline subprocess dies with it (no automatic recovery of an in-progress detection run).
- CPU/GPU resource limits set on the `api` container apply to the pipeline too, since they're the same container. For a CPU-bound YOLO pipeline, this is fine for a demo; for a real production deployment, running the pipeline as its own container/process — with its own resource limits — would be the more scalable design, but that's a larger architectural change out of scope for this pass.
- Model weights (`runs/detect/*/weights/best.pt`) and test videos need to be present inside the container for the pipeline subprocess to find them — handled here via volume mounts (see `docker-compose.yml`) rather than baking multi-GB model weights into the image itself, which would make image builds slow and images enormous.

### 3. RTSP camera sources reachable from inside the container

If a camera's `source` field is an `rtsp://` URL pointing at a device on your LAN (e.g. `rtsp://192.168.1.50:554/stream`), the `api` container needs network access to that address. With Docker's default bridge networking this generally works fine for LAN-reachable IPs, but if a camera is only reachable via `localhost` on the host machine (e.g. a local RTSP test server like `mediamtx` running directly on the host, as used in local dev/testing), the container will need `host.docker.internal` (Mac/Windows) or `--network host` (Linux) to reach it — plain `localhost` inside the container refers to the container, not the host.

## Environment variables

| Variable | Default (in compose) | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql://omnix:omnix_dev_password@postgres:5432/omnix` | Points at the `postgres` service by name — the only DB-related thing that differs from local dev's `.env` |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | CORS — set to your deployed frontend's real URL in a non-local deployment |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Used to build screenshot URLs returned to the frontend — set to the API's real public address in a non-local deployment |
| `VIDEO_SOURCE` | `test_video.mp4` | Fallback source for camera 1 if its DB row has no real source set (see `rtsp_design.md`) |
| `OLLAMA_MODEL` | `llama3.2:3b` | Model name requested from Ollama — see "What does NOT containerize" above regarding the Ollama host itself |

## Volumes

- `omnix_pg_data` — Postgres data directory, survives `docker compose down` (not `down -v`)
- `omnix_incidents` — incident screenshots (`incidents/*.jpg`), same persistence behavior
- `./runs`, model weight files, and test videos are **bind-mounted** rather than copied into the image, since they're multi-GB and change independently of application code — baking them into the image would make every rebuild slow and bloat image size unnecessarily
| `SMTP_HOST` | (none) | SMTP server for outgoing alert emails. If unset, email notifications silently no-op regardless of the Settings toggle |
| `SMTP_PORT` | `587` | SMTP port (STARTTLS) |
| `SMTP_USER` | (none) | SMTP auth username, if your provider requires it |
| `SMTP_PASSWORD` | (none) | SMTP auth password |
| `SMTP_FROM` | `SMTP_USER` or `omnix-alerts@localhost` | From address on outgoing alert emails |
| `ALERT_EMAIL_TO` | (none) | Comma-separated recipient list. If unset, email notifications silently no-op |
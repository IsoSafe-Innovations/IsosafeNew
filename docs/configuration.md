# Configuration

Every tunable is an environment variable. The backend reads them through
`pydantic-settings` in [backend/app/config.py](../backend/app/config.py)
(`Settings`, cached by `get_settings()`), which also loads a `.env` file from
the working directory. In Docker, both `backend` and `inference` receive the
project-root `.env` via `env_file`, and Compose overrides `DATABASE_URL` and
`REDIS_URL` with in-network addresses.

Settings are read once per process. **Changing a variable requires restarting
the affected container** (`docker compose up -d backend inference` after editing
`.env`).

The "Used by" column tells you which container needs the restart: **API** =
`backend`, **Pipeline** = `inference`.

## Infrastructure

| Variable | Default (code) | Used by | Description |
|---|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://isosafe:isosafe@localhost:5432/isosafe` | API, Pipeline | SQLAlchemy async URL. Alembic derives a psycopg2 URL from it; the raw asyncpg pool strips `+asyncpg`. Overridden by Compose. |
| `REDIS_URL` | `redis://localhost:6379/0` | API, Pipeline | Overridden by Compose. |
| `MEDIA_ROOT` | `/data/media` | API, Pipeline | Root of the shared media volume: `snapshots/`, `uploads/`, `heatmaps/`. The API also mounts it at `/media` if the directory exists. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `isosafe` / `isosafe` / `isosafe` (Compose) | Compose | Used by Compose to initialise Postgres and build `DATABASE_URL`. |
| `HTTP_PORT` / `HTTPS_PORT` | `80` / `443` | Compose | Host ports published by nginx. |
| `API_WORKERS` | `2` | Compose | Gunicorn worker count for the API. |

## Authentication

| Variable | Default | Used by | Description |
|---|---|---|---|
| `JWT_SECRET` | `dev-secret-do-not-use-in-prod` | API | HS256 signing key. Changing it invalidates every issued token. |
| `ACCESS_TOKEN_MINUTES` | `30` | API | Access-token lifetime. |
| `REFRESH_TOKEN_DAYS` | `7` | API | Refresh-token lifetime. |
| `CORS_ORIGINS` | `http://localhost:5173` | API | Comma-separated allowed origins. |
| `BOOTSTRAP_ADMIN_EMAIL` | `admin@isosafe.local` | API | Read with `os.environ` at startup. Only used when `users` is empty. |
| `BOOTSTRAP_ADMIN_PASSWORD` | *(empty → random, logged once)* | API | As above. |

## Detection

| Variable | Default | Used by | Description |
|---|---|---|---|
| `PERSON_CONFIDENCE` | `0.40` | Pipeline | Minimum YOLO confidence for `person`. |
| `VEHICLE_CONFIDENCE` | `0.35` | Pipeline | Minimum confidence for every non-person class (`car`, `motorcycle`, `bus`, `truck`, and also `backpack`, `suitcase`). |
| `PLATE_CONFIDENCE` | `0.20` | Pipeline | Minimum EasyOCR confidence to accept a plate read. |
| `YOLO_MODEL` | `yolov8n.pt` | Pipeline | Ultralytics model name or path. Larger models (`yolov8s.pt`, `yolov8m.pt`) are more accurate and slower. |
| `YOLO_DEVICE` | `cpu` | Pipeline | `cpu`, `cuda`, `cuda:0`, … |
| `INFERENCE_MAX_DIM` | `640` | Pipeline | Frames are downscaled so the longest side is at most this before YOLO. |

## Pipeline cadence and capacity

| Variable | Default | Used by | Description |
|---|---|---|---|
| `PROCESS_EVERY_N_FRAMES` | `3` | Pipeline | RTSP/file readers enqueue only every Nth frame. At 25 fps source, 3 → ~8 fps offered to inference. Not applied to snapshot URLs. |
| `OCR_EVERY_N_FRAMES` | `5` | Pipeline | Plate OCR runs for vehicle tracks on every Nth *processed* frame of a camera. |
| `INFERENCE_WORKERS` | `2` (code) / `1` (`.env.example`) | Pipeline | YOLO worker processes. Each holds its own model copy. Use `1` on GPU. |
| `INFERENCE_BATCH_SIZE` | `8` | Pipeline | Max frames per YOLO call (one per camera per batch). |
| `MAX_CAMERAS_PER_NODE` | `64` | API, Pipeline | API refuses to create more cameras; pipeline refuses to start more streams. |
| `FILE_PLAYBACK_FPS` | `0` | Pipeline | Read pace for `file` sources; `0` = the video's native FPS. Clamped to 5–30. |
| `DASHBOARD_MAX_FPS` | `10` | Pipeline | Max frames/s published per camera to the dashboard. Clamped to 2–30. |
| `FRAME_JPEG_QUALITY` | `70` | Pipeline | JPEG quality of dashboard frames (longest side capped at 960 px). |
| `WORKER_MEMORY_LIMIT_MB` | `4096` | Pipeline | RSS of the pipeline + its children. Exceeding it fires a critical self-alert and exits (Docker restarts the container). |
| `DISK_MIN_FREE_GB` | `2.0` | Pipeline | Below this free space on `MEDIA_ROOT`, snapshot writes pause and a critical self-alert fires. Resumes above 1.5× the threshold. |

## Rule defaults

Used when a rule omits the corresponding field. See
[Rules, zones and profiles](rules-and-zones.md).

| Variable | Default | Applies to |
|---|---|---|
| `LOITER_SECONDS` | `30` | `loitering.threshold_seconds` |
| `STOPPED_VEHICLE_SECONDS` | `10` | `stopped_vehicle.threshold_seconds` |
| `STOPPED_PIXEL_DELTA` | `15` | Movement tolerance for `stopped_vehicle` and `abandoned_object`, in pixels of a 640 px frame (15 → 0.0234 normalized). |
| `INCIDENT_COOLDOWN_SECS` | `30` | `cooldown_seconds` of any rule |
| `QUEUE_ZONE_THRESHOLD` | `5` | `queue_threshold.threshold_count` |

## Retention

| Variable | Default | Used by | Description |
|---|---|---|---|
| `RETENTION_DETECTIONS_DAYS` | `90` | Migration | Read **once, when migration 0001 runs**, to create the TimescaleDB retention policy on `detections`. Changing it later has no effect; see [Database › Retention](database.md#retention). |
| `RETENTION_SNAPSHOTS_DAYS` | `30` | Pipeline | Nightly job deletes snapshot files older than this (by mtime). |

## Alerts

| Variable | Default | Used by | Description |
|---|---|---|---|
| `SMTP_HOST` | *(empty = email off)* | Pipeline | SMTP server. STARTTLS is always issued. |
| `SMTP_PORT` | `587` | Pipeline | |
| `SMTP_USER` / `SMTP_PASSWORD` | *(empty)* | Pipeline | Login is skipped when `SMTP_USER` is empty. |
| `SMTP_FROM` | `alerts@isosafe.local` | Pipeline | |
| `ALERT_EMAIL_TO` | *(empty = email off)* | Pipeline | Single recipient address (the value goes into the `To` header as-is). |
| `ALERT_EMAIL_MIN_SEVERITY` | `critical` | Pipeline | `info`, `warning`, or `critical`. |
| `WEBHOOK_URL` | *(empty = off)* | Pipeline | Receives every incident as JSON POST. |
| `WEBHOOK_SECRET` | *(empty = unsigned)* | Pipeline | Adds `X-IsoSafe-Signature: sha256=<hex HMAC of body>`. |

## AI (optional)

| Variable | Default | Used by | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | *(empty = AI off)* | API | Enables `/api/search` and AI insights. |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | API | Model id for both features. |

## Security and limits

| Variable | Default | Used by | Description |
|---|---|---|---|
| `FERNET_KEY` | *(empty = plaintext)* | API, Pipeline | Encrypts camera `source` at rest. Must be identical in both containers (it is, via the shared `.env`). |
| `UPLOAD_MAX_MB` | `500` | API | Upload size cap (nginx also caps request bodies at 512 MB). |

## Hard-coded constants worth knowing

These are not configurable without a code change.

| Constant | Value | Location |
|---|---|---|
| Camera reconcile interval | 15 s | `pipeline/runner.py` `RECONCILE_INTERVAL` |
| Frame queue size | 2 | `ingestion/streams.py` |
| Reconnect backoff | 1, 2, 4, 8, 16, 30 s | `ingestion/streams.py` |
| Tracker match gate | 0.12 (normalized) | `inference/tracker.py` |
| Track expiry | 30 processed frames unseen | `inference/tracker.py` |
| Track history | 300 points | `inference/tracker.py` |
| Plate dedup window | 60 s per track | `inference/ocr.py` |
| Detection flush | 2 s or 200 rows | `inference/writer.py` |
| Analytics upsert interval | 300 s | `analytics/jobs.py` |
| Nightly maintenance | 02:00 UTC | `analytics/jobs.py` |
| Heatmap grid | 32 × 32 | `pipeline/camera_worker.py`, `analytics/jobs.py` |
| Stuck upload timeout | 6 h | `analytics/jobs.py` |
| Resource guard interval | 30 s | `pipeline/guards.py` |
| AI insights interval | 3600 s | `main.py` |
| NL search timeout / row cap | 5 s / 100 rows | `search/nl_search.py` |
| WebSocket send queue | 30 messages | `ws/manager.py` |
| Backup time / retention | 02:30 UTC / 14 days | `deploy/backup.sh`, Compose |

## Example production `.env`

```dotenv
POSTGRES_USER=isosafe
POSTGRES_PASSWORD=<long random>
POSTGRES_DB=isosafe
API_WORKERS=2

JWT_SECRET=<long random>
FERNET_KEY=<Fernet.generate_key()>
BOOTSTRAP_ADMIN_EMAIL=secops@acme.lan
BOOTSTRAP_ADMIN_PASSWORD=<temporary, change after login>
CORS_ORIGINS=https://isosafe.acme.lan

YOLO_MODEL=yolov8s.pt
YOLO_DEVICE=cuda
INFERENCE_WORKERS=1
INFERENCE_BATCH_SIZE=16
PROCESS_EVERY_N_FRAMES=3

SMTP_HOST=smtp.acme.lan
SMTP_FROM=isosafe@acme.lan
ALERT_EMAIL_TO=soc@acme.lan
ALERT_EMAIL_MIN_SEVERITY=critical
WEBHOOK_URL=https://soar.acme.lan/hooks/isosafe
WEBHOOK_SECRET=<long random>

RETENTION_DETECTIONS_DAYS=90
RETENTION_SNAPSHOTS_DAYS=30
```

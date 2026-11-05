# Iso Safe — AI Video Intelligence Platform

Iso Safe adds an AI intelligence layer to CCTV infrastructure the customer already
owns. One on-premises node per building ingests 16–64 camera streams, runs
YOLOv8 + OCR + behavioral rules on every feed, and turns raw video into security
alerts, operational metrics, and business insights — with sub-second alert latency.

**Privacy model:** all video processing and storage stays on the customer's
network. The only external call is optional query text to the Anthropic API for
natural-language search and AI insights. No video, frames, or database rows ever
leave the network.

## Architecture

```
cameras (RTSP / snapshot / file)
   │  asyncio readers, bounded queues (drop-oldest, always-fresh frames)
   ▼
inference workers (ProcessPoolExecutor, YOLOv8 batched across cameras, EasyOCR)
   │  centroid tracking, zone tagging
   ├──► PostgreSQL 16 + TimescaleDB  (batched writes, 90-day retention)
   ├──► rule engine ──► incidents + annotated snapshots ──► Redis pub/sub
   │                                                            │
   ▼                                                            ▼
analytics jobs (hourly buckets, heatmaps, nightly rollups)   alert fanout
                                                             (WebSocket / email / webhook)
   ▼
FastAPI + React dashboard (JWT auth, role-based, 20 concurrent operators)
```

Services (Docker Compose): `postgres` (TimescaleDB), `redis`, `backend` (Gunicorn +
Uvicorn API), `inference` (detection pipeline), `frontend` (nginx-served Vite
build), `nginx` (TLS termination + reverse proxy), `prometheus`, `backup`
(nightly pg_dump, 14-day rotation).

## Quick start

For AWS EC2 + private S3 deployment, follow [the AWS deployment guide](deploy/AWS.md).
Camera inference runs on a separate on-site agent in this mode.

```bash
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, JWT_SECRET, FERNET_KEY (see below),
# BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD, and optionally ANTHROPIC_API_KEY.

# Generate a Fernet key for camera-credential encryption at rest:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# TLS certs for nginx (self-signed for LAN deployments):
mkdir -p deploy/certs
openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
  -keyout deploy/certs/server.key -out deploy/certs/server.crt -subj "/CN=isosafe"

docker compose up -d --build
```

Open `https://<host>/` and sign in with the bootstrap admin credentials. The
first admin user is created automatically on first startup.

- API docs: `https://<host>/api/docs`
- Health: `GET /api/health` · Metrics: `GET /api/metrics` (Prometheus format)

## Adding cameras

For per-camera AI quality, tracking, plate reading, live analysis health, and
accuracy checks, see [the analysis improvement guide](docs/analysis-improvements.md).

Admins can use **Cameras → Add live link**, choose **YouTube live link**, and
paste a public HTTPS watch/short/live video URL. The camera tile uses YouTube's
embedded player for smooth playback, with muted autoplay, sound controls and
full screen. Playback does not wait for inference. Server-side analysis uses
yt-dlp to resolve a fresh stream on reconnect; the cloud `upload-worker` handles
YouTube cameras as well as uploaded recordings. YouTube streams are excluded
from on-site agents to avoid duplicate processing. Docker includes Node for
yt-dlp's JavaScript solver; native installs also need Node 22+ on PATH.

YouTube controls live latency, embedding, geographic restrictions and access.
Private/restricted streams or YouTube bot checks may prevent analysis even when
browser playback works. The UI reports analysis separately from playback.
An initial real-link decoding check of `Q71sLS8h9a4` received a 1280×720 frame
in 10.7 seconds (including URL resolution); this is startup time, not a measured
end-to-end live delay or a performance guarantee.

Operators and admins can use **Cameras → Upload video** to upload a recording
(up to 500 MB by default), name it, and play it repeatedly as a camera source.
The cloud stack includes an `upload-worker` service so website uploads run
without an on-site agent. Uploads use server disk space and cloud CPU for
detection; deleting an uploaded camera removes its video. The first video may
take longer while the detection model downloads and initializes.

1. **Cameras → Add camera** (admin role). Source types: `rtsp`
   (`rtsp://user:pass@ip:554/stream`), `snapshot_url` (HTTP JPEG polling), and
   `file` (looped playback for demos).
2. Or use **ONVIF Discovery** to scan the local subnet and approve candidates.
3. Pick a **vertical profile** (retail, supermarket, mall, bank, hotel,
   restaurant, hospital, school, manufacturing, warehouse, logistics, office,
   estate, fuel_station) to pre-populate rules — the camera is monitored with
   zero manual rule creation, and everything stays editable.
4. Draw zones (polygons or perimeter lines) over the live frame in the camera
   editor and attach rules from templates.

Rule types: `loitering`, `stopped_vehicle`, `zone_intrusion`,
`after_hours_activity`, `queue_threshold`, `crowd_density`, `line_crossing`,
`abandoned_object`. Rules and zones are data (JSONB on the camera row); the
pipeline picks up edits within 15 seconds without restarts.

## Roles

| Role | Access |
|---|---|
| `viewer` | read-only: dashboards, incidents, analytics, reports, search |
| `operator` | viewer + incident management (status, assignment, notes) + uploads |
| `admin` | full access: cameras, zones, rules, users, discovery |

## Configuration

Every tunable is an environment variable (see `.env.example`): detection
confidence thresholds, frame cadence (`PROCESS_EVERY_N_FRAMES`), rule defaults
(`LOITER_SECONDS`, `STOPPED_VEHICLE_SECONDS`, …), capacity
(`MAX_CAMERAS_PER_NODE`, `INFERENCE_WORKERS`), retention
(`RETENTION_DETECTIONS_DAYS`, `RETENTION_SNAPSHOTS_DAYS`), alert channels
(SMTP, HMAC-signed webhooks), and the optional `ANTHROPIC_API_KEY`.

GPU nodes: set `INFERENCE_WORKERS=1`, `YOLO_DEVICE=cuda`, and uncomment the GPU
reservation in `docker-compose.yml`. Frames are batched across cameras into
single YOLO calls.

## AI features (optional)

With `ANTHROPIC_API_KEY` set:

- **AI Assistant** — natural-language questions become validated SELECT-only SQL
  (allowlist parser rejects mutations, comments, semicolons, and system catalogs;
  5s statement timeout; 100-row cap). The SQL and explanation are always shown.
- **AI Insights** — hourly digest of analytics + open incidents produces 3–6
  actionable observations, cached in Redis.

Without the key, both degrade gracefully with a clear message; everything else
runs unaffected.

## Operations

- **Backups:** nightly `pg_dump` to `deploy/backups/` with 14-day rotation.
  Restore procedure: `deploy/RESTORE.md`.
- **Crash recovery:** every service has a restart policy; the pipeline
  reconciles camera tasks from the database on startup; stuck upload jobs are
  timed out; broken inference worker pools are rebuilt automatically.
- **Resource guards:** memory ceiling triggers a clean process recycle; a disk
  space monitor pauses snapshot writes and fires a critical self-alert.
- **Audit:** all admin mutations are recorded in the `audit_log` table.
  RTSP credentials are Fernet-encrypted at rest.

## Development

```bash
# Backend (Python 3.11+)
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt
.venv/Scripts/python -m pytest tests        # unit tests
.venv/Scripts/python -m uvicorn app.main:app --reload   # API
.venv/Scripts/python -m app.pipeline.runner              # detection pipeline

# Frontend (Node 22.13+ LTS or Node 24)
cd frontend
npm install && npm run dev                   # http://localhost:5173, proxies /api

# Benchmarks / acceptance harnesses
python -m scripts.bench_detections           # 1M-row insert + query timing
python -m scripts.smoke_api http://localhost:8000   # end-to-end API checks
python -m scripts.load_test                  # streams + WS clients + API load soak
```

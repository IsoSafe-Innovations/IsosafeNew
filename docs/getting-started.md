# Getting Started

Two paths: a **production-style install** with Docker Compose (what a customer
node runs), and a **local development** setup where you run the API, pipeline,
and frontend directly.

## Prerequisites

| Path | Requirements |
|---|---|
| Docker install | Docker Engine 24+ with Compose v2; 4+ CPU cores and 8 GB RAM for a handful of cameras (see [Operations › Sizing](operations.md#sizing)); OpenSSL for certificates |
| Local dev | Python 3.11+, Node 20+, a PostgreSQL 16 server (TimescaleDB optional) and Redis 7 reachable from your machine |
| GPU (optional) | NVIDIA driver + NVIDIA Container Toolkit |

The first build downloads PyTorch (CPU wheels), Ultralytics, and EasyOCR. On
first run Ultralytics downloads the YOLO weights (`yolov8n.pt`, ~6 MB) into the
`models` volume, and EasyOCR downloads its English model on the first plate read.
The node therefore needs internet access the first time, or you must pre-seed
those files (see [Operations › Air-gapped installs](operations.md#air-gapped-installs)).

## Production install (Docker Compose)

### 1. Create the environment file

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

| Variable | Why |
|---|---|
| `POSTGRES_PASSWORD` | Database password. Compose builds `DATABASE_URL` for the containers from `POSTGRES_*`, so you don't need to edit `DATABASE_URL` for Docker. |
| `JWT_SECRET` | Signs every token. Use a long random string. |
| `FERNET_KEY` | Encrypts camera source URLs (and their credentials) at rest. |
| `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` | First admin account, created only when the `users` table is empty. |
| `CORS_ORIGINS` | The URL operators will browse to, e.g. `https://isosafe.lan`. |

Generate secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> Set `FERNET_KEY` **before** adding cameras and never change it afterwards.
> Sources saved with one key can't be decrypted with another; the pipeline will
> log `cannot decrypt source` and skip those cameras. See
> [Security › Rotating the Fernet key](security.md#rotating-the-fernet-key).

Everything else has working defaults; see [Configuration](configuration.md).

### 2. Create TLS certificates

nginx expects `deploy/certs/server.crt` and `deploy/certs/server.key`. For a LAN
deployment a self-signed certificate is fine:

```bash
mkdir -p deploy/certs
openssl req -x509 -newkey rsa:2048 -nodes -days 825 -keyout deploy/certs/server.key -out deploy/certs/server.crt -subj "/CN=isosafe"
```

Use your organization's CA-issued certificate if one is available, so browsers
don't warn.

### 3. Start the stack

```bash
docker compose up -d --build
```

Startup order is enforced by health checks: postgres and redis become healthy →
`backend` runs `alembic upgrade head` then starts Gunicorn → `inference` starts
the pipeline. Watch progress with:

```bash
docker compose logs -f backend inference
```

### 4. Sign in

Browse to `https://<host>/` and log in with the bootstrap admin credentials. If
you left `BOOTSTRAP_ADMIN_PASSWORD` empty, a random 12-character password is
generated and printed once in the backend log as
`bootstrap admin created: <email> / <password>`.

Useful URLs:

| URL | Purpose |
|---|---|
| `https://<host>/api/health` | Database + Redis health |
| `https://<host>/api/metrics` | Prometheus metrics |

> **API docs:** FastAPI serves Swagger UI at `/docs` and the schema at
> `/openapi.json` (its defaults). Behind nginx, `/docs` is routed to the SPA and
> `/api/docs` reaches the backend but 404s, so the interactive docs are not
> reachable through the proxy as shipped. In development open
> `http://localhost:8000/docs`; in Docker use
> `docker compose exec backend curl -s localhost:8000/openapi.json`. See
> [Known issues](known-issues.md).

### 5. Add your first camera

1. Go to **Cameras → Add camera** (admin only).
2. Choose a source type:
   - **RTSP stream** — `rtsp://user:pass@10.0.0.5:554/stream1`
   - **HTTP snapshot URL** — a URL that returns a JPEG; polled every
     `refresh_secs` (default 2 s)
   - **Video file** — a path inside the inference container, looped forever. The
     bundled samples are at `/data/sample_videos/vtest.avi`,
     `/data/sample_videos/demo.mp4`, `/data/sample_videos/sample2.mp4`.
3. Optionally pick a **vertical profile** (retail, bank, warehouse, …) to
   pre-load a rule set.
4. Save. The pipeline picks the camera up within 15 seconds and the tile goes
   live on the Cameras and Dashboard pages.
5. Click the tile to open the editor, draw zones over the live frame, and adjust
   rules. See [Rules, zones and profiles](rules-and-zones.md).

### Demo in five minutes

Add a camera named "Lobby demo", type **Video file**, source
`/data/sample_videos/vtest.avi` (a pedestrian clip), profile **None**. Open the
editor and add a **Loitering** rule from the template with threshold 10 s. Within
a minute you should see person boxes on the live tile, a loitering alert in the
bell menu and on **AI Alerts**, and a new row in **Incidents** with an annotated
snapshot.

## Local development

### Backend

```bash
cd backend
python -m venv .venv
```

Activate it (`source .venv/bin/activate` on Linux/macOS, `.venv\Scripts\activate`
on Windows), then:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

Point the app at your local services. `Settings` reads a `.env` file from the
**current working directory**, so create `backend/.env` (or export variables):

```dotenv
DATABASE_URL=postgresql+asyncpg://isosafe:isosafe@localhost:5432/isosafe
REDIS_URL=redis://localhost:6379/0
MEDIA_ROOT=./media
JWT_SECRET=dev-only
BOOTSTRAP_ADMIN_PASSWORD=admin12345
CORS_ORIGINS=http://localhost:5173
```

> `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` are read with
> `os.environ`, not through `Settings`, so they must be real environment variables
> when running outside Docker (a `.env` file alone is not enough). The quickest
> alternative is to let the app generate a password and read it from the log, or
> run `python -m scripts.reset_admin <email> <password>` afterwards.

Create the schema and run the two processes in separate terminals:

```bash
alembic upgrade head
```

```bash
python -m uvicorn app.main:app --reload
```

```bash
python -m app.pipeline.runner
```

The fastest way to get PostgreSQL + Redis locally is to start just those two
services from the compose file and publish their ports, e.g. with a
`docker-compose.override.yml`:

```yaml
services:
  postgres:
    ports: ["5432:5432"]
  redis:
    ports: ["6379:6379"]
```

```bash
docker compose up -d postgres redis
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Vite serves on `http://localhost:5173` and proxies `/api` (including the
WebSocket) and `/media` to `http://localhost:8000`.

### Run the tests

```bash
cd backend
python -m pytest tests
```

The unit tests need no database, Redis, or model. See
[Development](development.md) for the integration harnesses.

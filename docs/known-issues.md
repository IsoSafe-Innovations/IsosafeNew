# Known Issues and Limitations

Found while documenting the code (October 2026), plus the items already tracked
in the [PRD §0.2](PRD-MVP-v1-Developer-Edition.md#02-known-bugs--tech-debt-fix-not-optional-for-production-hardening).
Each entry gives the location, the effect, and a suggested fix. Severity is a
judgement of operational impact.

## High

### Uploads are re-processed and never complete

- **Where:** `app/api/uploads.py`, `app/ingestion/streams.py` (`run()` returns
  after one pass when `loop_file=false`), `app/pipeline/runner.py` (`reconcile()`
  restarts any stream task that is `done()`).
- **Effect:** When an uploaded video finishes, its stream task ends; 15 s later
  the reconciler treats it as dead and restarts it, so the file is analysed
  again and again, duplicating detections and inflating analytics. Nothing ever
  sets `upload_jobs.status = 'done'` or `completed_at`; the nightly job marks
  jobs `error` / `timed out` after 6 h. The upload camera stays enabled
  indefinitely.
- **Fix:** When a single-pass stream finishes, mark the job `done`, set
  `completed_at`, and disable the camera (or have the reconciler skip finished
  single-pass streams).

### Hourly analytics upsert

- **Where:** `HOURLY_UPSERT` in `app/analytics/jobs.py`.
- **Effect:** PRD §0.2 reports `GroupingError: subquery uses ungrouped column
  "d.ts"`; when it fails, `analytics_hourly` doesn't update, which empties the
  Analytics charts, the dashboard KPIs, reports' footfall figures, and AI
  insights' input. Even when it runs, the four correlated LATERAL subqueries
  execute per detection row, which scales poorly with detection volume. Also,
  only the current hour is recomputed every 5 minutes, so up to the last 5
  minutes of each hour are never aggregated.
- **Fix:** Rewrite as independent aggregates per `(camera_id, bucket)` joined
  together (or TimescaleDB continuous aggregates), and on each run recompute
  both the previous and current hour.

### Pipeline metrics are not exposed to Prometheus

- **Where:** `app/metrics.py` objects are incremented in the `inference`
  process; only the API process serves `/api/metrics`.
- **Effect:** Frames, drops, inference latency, detections, incidents, camera
  FPS, reconnects, and alert latency never reach Prometheus. API metrics are also
  per-Gunicorn-worker.
- **Fix:** `prometheus_client.start_http_server(9100)` in the pipeline and a
  scrape target for `inference:9100`; multiprocess mode for Gunicorn.

## Medium

### Rate limits are global behind nginx

- **Where:** `rate_limit()` in `app/api/deps.py` keys on `request.client.host`.
- **Effect:** Behind the bundled nginx every request comes from the nginx
  container's IP, so login (10/min), search (20/min), and insights refresh (4/h)
  are shared by all users on the node.
- **Fix:** Key on `X-Real-IP` (already set by nginx), or run Uvicorn with
  `--proxy-headers --forwarded-allow-ips` and have nginx send `X-Forwarded-For`.

### Media files are unauthenticated

- **Where:** `location /media/` in `deploy/nginx.conf`; `StaticFiles` mount in
  `app/main.py`.
- **Effect:** Snapshots, uploads, and heatmaps are downloadable by anyone who can
  reach the node and knows the path.
- **Fix:** nginx `auth_request` against a token-checking endpoint, or signed
  short-lived URLs. See [Security › Media files](security.md#media-files).

### Annotated frames rarely reach the dashboard

- **Where:** `CameraProcessor.publish_preview()` and `_publish()` share one
  throttle in `app/pipeline/camera_worker.py`.
- **Effect:** The un-annotated preview is published just before inference and
  resets the throttle, so the annotated frame afterwards is usually skipped;
  bounding boxes flicker or are absent on fast nodes. `file` sources never
  publish annotated frames at all, so demos show no boxes.
- **Fix:** Use separate throttles, or publish previews only when the last
  annotated frame is older than the interval.

### GPU requires a CUDA build of PyTorch

- **Where:** `backend/Dockerfile` installs CPU wheels via `TORCH_INDEX`; the
  README says to set `YOLO_DEVICE=cuda` and uncomment the GPU reservation.
- **Effect:** Following the README alone fails to use the GPU.
- **Fix:** Document/pass a CUDA `TORCH_INDEX` build arg (see
  [Operations › GPU nodes](operations.md#gpu-nodes)).

### API docs not reachable through nginx

- **Where:** `FastAPI(...)` in `app/main.py` uses default `docs_url="/docs"`,
  `openapi_url="/openapi.json"`; nginx only proxies `/api/` to the backend.
- **Effect:** The README's `https://<host>/api/docs` returns 404.
- **Fix:** `FastAPI(docs_url="/api/docs", openapi_url="/api/openapi.json")` and
  update `scripts/smoke_api.py`, which requests `/openapi.json`.

### Rule schedules run on UTC

- **Where:** `CameraRuleEngine.evaluate()` uses `datetime.now()` (container
  local time); the image sets no `TZ`.
- **Effect:** After-hours windows like `22:00-06:00` are evaluated in UTC, which
  is wrong for any site not on UTC.
- **Fix:** Add a per-node `SITE_TIMEZONE` setting (or per-camera timezone) and
  evaluate with `zoneinfo`.

### Backup service may restart-loop

- **Where:** `deploy/backup.sh` uses `date -d "tomorrow 02:30"` with a BSD
  fallback, under `set -eu`.
- **Effect:** If the image's `date` supports neither form, the script exits and
  no backups are made (also listed in PRD §0.2).
- **Fix:** Compute the delay arithmetically (seconds since midnight UTC), or use
  cron in the container.

### NL search rejects some valid queries

- **Where:** `app/search/validator.py`.
- **Effect:** `EXTRACT(hour FROM bucket)`, `SUBSTRING(x FROM 1)`, and
  `generate_series(...)` are rejected as "Table not allowed" because the regex
  treats any word after `FROM` as a table. Any forbidden keyword inside a string
  literal or alias (`'%lock%'`, `AS set`) is rejected too. Questions like "What
  was the busiest hour yesterday?" — one of the UI's example prompts — can fail.
- **Fix:** Use a real SQL parser (e.g. `sqlglot`) to walk table references and
  statement types; keep the read-only transaction and timeout. Optionally tell
  the model to prefer `date_part('hour', ...)`.

## Low

### Camera behaviour

- Only `zones` and `rules` hot-reload. Changes to `source`, `type`,
  `refresh_secs`, or `loop_file` need the camera disabled/re-enabled or a
  pipeline restart (`reconcile()` in `runner.py`).
- With more cameras than `INFERENCE_BATCH_SIZE`, batches favour cameras earlier
  in insertion order under sustained load (`_collect_batch`).
- ONVIF discovery uses multicast, which doesn't cross Docker's bridge network,
  and the UI's **Use** button fills the ONVIF service URL (`xaddr`) as an RTSP
  source instead of calling `/api/cameras/discover/stream-uri`.

### Profiles

- `plate_logging`, `kpi_cards`, and `default_reports` are defined but unused;
  OCR runs on every vehicle on every camera (PRD §0.2).
- A profile's rules are applied only on camera creation with empty rules;
  changing `vertical_profile` via PATCH doesn't re-apply them.
- Profile rules referencing undrawn zones run on the whole frame, which makes
  `zone_intrusion` on `restricted` fire for every person.

### Analytics and data

- Footfall counts distinct track ids per hour; track ids restart on every
  pipeline restart and fragment on occlusion.
- Heatmap files and uploaded videos are never pruned.
- `RETENTION_DETECTIONS_DAYS` is read only by the initial migration; changing it
  later has no effect. On plain PostgreSQL there's no detection retention.
- `analytics_daily` is populated but no endpoint or screen uses it.
- The `camera_health` report contains configuration only, no health data.
- No foreign keys: deleting a camera leaves orphaned detections, incidents, and
  analytics.

### AI insights

- The insights loop runs in every Gunicorn worker (`API_WORKERS=2` → two model
  calls per hour) and first runs one hour after startup.

### Auth and security

- No token revocation; logout is client-side only.
- WebSocket token in the query string can appear in access logs; an open socket
  outlives token expiry.
- No protection against deleting or demoting the last admin.
- Snapshot-URL sources with credentials in query parameters aren't redacted in
  API responses (`redact_source` only handles `user:pass@`).
- `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` are read from
  `os.environ`, not `Settings`, so a local `.env` file doesn't set them in
  development.
- `scripts/reset_admin.py` defaults to the password `admin123` when called
  without arguments.
- The app starts with the default `JWT_SECRET` if none is configured.

### Alerts

- System self-alerts (memory, disk) aren't stored as incidents, so they're lost
  if no one is watching and email/webhook aren't configured.
- Email and webhook have no retry; alerts published while the inference
  container is down are never dispatched.
- Email only supports STARTTLS, a single recipient, and has no snapshot.

### Configuration and docs drift

- `INFERENCE_WORKERS` defaults to `2` in code and `1` in `.env.example`.
- `INFERENCE_BATCH_SIZE`, `INFERENCE_MAX_DIM`, `DISK_MIN_FREE_GB` exist in
  `Settings` but not in `.env.example`.

### Frontend

- The Upload panel is on the admin-only page although operators may upload.
- No UI to reset another user's password, edit rule schedules/cooldowns, or
  choose report date ranges.
- The role is cached in `localStorage`; role changes show after re-login.

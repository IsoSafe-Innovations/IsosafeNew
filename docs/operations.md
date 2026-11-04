# Operations

Running an Iso Safe node day to day: deployment, capacity, GPU, monitoring,
backups, and troubleshooting. Initial install is in
[Getting started](getting-started.md).

## Deployment model

One node = one Docker Compose stack, typically one per building. Nodes are
independent: there is no central server, cross-site dashboard, or replication.
All state is in the `pgdata` and `media` volumes plus `.env` and `deploy/certs`.

### Common commands

```bash
docker compose ps
```

```bash
docker compose logs -f --tail=200 inference
```

```bash
docker compose restart inference
```

```bash
docker compose exec postgres psql -U isosafe -d isosafe
```

```bash
docker compose exec redis redis-cli
```

### Upgrading

```bash
git pull
```

```bash
docker compose up -d --build
```

The backend runs `alembic upgrade head` on start, so migrations apply
automatically. Take a fresh backup first (see [Backups](#backups)). The inference
container restarts with the new image and restores all cameras within 15 s.
Live trackers, rule timers, and session counts reset on every pipeline restart.

### Restart behaviour

Every service uses `restart: unless-stopped`. On top of that:

| Failure | Recovery |
|---|---|
| Camera stream drops | Reconnect with 1→30 s backoff, forever |
| Stream task crashes | Reconcile loop restarts it within 15 s |
| YOLO worker process dies | Pool rebuilt, batch retried once |
| Pipeline memory > `WORKER_MEMORY_LIMIT_MB` | Process exits, Docker restarts it, cameras reconciled from DB |
| DB unavailable during detection flush | Rows re-buffered (max 400), retried every 2 s |
| Redis hiccup | Dispatcher and WebSocket pump resubscribe after 2–3 s |
| Disk nearly full | Snapshots paused, critical alert, resume automatically |

## Sizing

Capacity is driven by **processed frames per second across all cameras**:

```
offered load ≈ Σ(camera source fps) / PROCESS_EVERY_N_FRAMES   (+ snapshot cameras at 1/refresh_secs)
```

Inference throughput must keep up with that, or frames are dropped (by design —
see [Pipeline › Drop-oldest](pipeline.md#drop-oldest-enqueue)). Dropping is not
an error: it lowers the effective frame rate per camera, which mostly affects
tracking continuity, fast line crossings, and dwell accuracy.

How to tell if a node is overloaded:

- `isosafe_frames_dropped_total` growing fast relative to processed frames.
- Camera health FPS (Admin → System Health) well below
  `source_fps / PROCESS_EVERY_N_FRAMES`.
- `isosafe_inference_latency_seconds` p95 approaching or exceeding one
  processed-frame interval.

Levers, roughly in order of impact:

| Lever | Effect |
|---|---|
| GPU (`YOLO_DEVICE=cuda`) | Largest throughput gain; enables larger batches and models |
| `PROCESS_EVERY_N_FRAMES` ↑ | Linear reduction of load; coarser tracking |
| `INFERENCE_MAX_DIM` ↓ (e.g. 480) | Faster inference; misses small/distant objects |
| `INFERENCE_WORKERS` ↑ (CPU only) | More parallel YOLO processes; each uses its own model memory and CPU |
| `INFERENCE_BATCH_SIZE` ↑ | Better GPU utilisation; set ≥ camera count on GPU |
| `OCR_EVERY_N_FRAMES` ↑ | EasyOCR on CPU is expensive on vehicle-heavy cameras |
| Smaller model (`yolov8n.pt`) | Default; larger models trade speed for accuracy |
| Use camera sub-streams | Lower-resolution RTSP sub-streams decode much faster |

Other resources:

- **Database growth** is dominated by `detections` (one row per object per
  processed frame). Watch `hypertable_detailed_size('detections')` for the first
  days and adjust retention (see [Database › Retention](database.md#retention)).
- **Media volume** grows with snapshots (one full-resolution JPEG per incident,
  pruned after `RETENTION_SNAPSHOTS_DAYS`), uploads, and heatmap JSON (never
  pruned).
- **Dashboard bandwidth**: each watched camera streams up to
  `DASHBOARD_MAX_FPS` JPEGs (≤ 960 px at quality `FRAME_JPEG_QUALITY`) per
  viewer. Unwatched cameras cost only small count messages.
- **API workers**: `API_WORKERS` Gunicorn processes; each maintains its own DB
  pools and Redis subscription.

## GPU nodes

The backend image installs **CPU-only PyTorch** (build arg `TORCH_INDEX`
defaults to the CPU wheel index). Setting `YOLO_DEVICE=cuda` alone is not
enough. To use an NVIDIA GPU:

1. Install the NVIDIA driver and NVIDIA Container Toolkit on the host.
2. Build the image with a CUDA wheel index matching your driver, e.g. in
   `docker-compose.yml`:

   ```yaml
   inference:
     build:
       context: ./backend
       args:
         TORCH_INDEX: https://download.pytorch.org/whl/cu121
   ```

3. Uncomment the `deploy.resources.reservations.devices` block on the
   `inference` service.
4. In `.env`: `YOLO_DEVICE=cuda`, `INFERENCE_WORKERS=1`, and a larger
   `INFERENCE_BATCH_SIZE` (e.g. 16–32).
5. Rebuild and verify: `docker compose exec inference python -c "import torch; print(torch.cuda.is_available())"`.

EasyOCR is hard-coded to `gpu=False` and stays on CPU.

## Air-gapped installs

Three things are fetched from the internet at build or run time:

| What | When | How to pre-seed |
|---|---|---|
| Docker images, pip and npm packages | build | build on a connected machine; `docker save` / `docker load` the images |
| YOLO weights (`yolov8n.pt`) | first pipeline start | copy the `.pt` into the `models` volume and set `YOLO_MODEL=/data/models/yolov8n.pt` |
| EasyOCR models | first plate read | copy `~/.EasyOCR/model/` from a connected run into the inference container's home (or bake it into the image) |

If EasyOCR can't initialise, plate reading is disabled for that process with a
log line; everything else works. If YOLO can't load, the worker pool fails and no
detections are produced — check the inference logs.

Without `ANTHROPIC_API_KEY` the node makes no outbound calls at runtime (other
than to cameras, SMTP, and the webhook you configure).

## Monitoring

### Health

- `GET /api/health` — database and Redis reachability from the API. Returns 200
  with `"status": "degraded"` on failure, so alert on the body, not the code.
- Admin → **System Health** — per-camera online/FPS/reconnects/dropped frames.
- `docker compose ps` — container restarts (a climbing restart count on
  `inference` usually means the memory guard is recycling it).

### Prometheus

The `prometheus` service scrapes `backend:8000/api/metrics` every 15 s
([deploy/prometheus.yml](../deploy/prometheus.yml)). It has no published port; add
`ports: ["9090:9090"]` or put Grafana on the same network to view it.

Limitations of the shipped setup:

- **Pipeline metrics are not scraped.** Frames, inference latency, detections,
  rule evaluations, incidents, camera FPS, and reconnects are recorded in the
  `inference` process, which exposes no metrics endpoint. Only API-process
  metrics (e.g. `isosafe_ws_clients`) reach Prometheus. To fix, start
  `prometheus_client.start_http_server(9100)` in `app.pipeline.runner.main()` and
  add `inference:9100` as a scrape target.
- **Gunicorn workers have separate registries.** Each scrape hits one worker, so
  values like `isosafe_ws_clients` reflect a single worker. Use
  `prometheus_client`'s multiprocess mode for accurate API metrics.

Suggested alerts once pipeline metrics are exposed:

| Alert | Expression (sketch) |
|---|---|
| Camera offline | `isosafe_camera_fps == 0` for 5 m |
| Heavy frame dropping | `rate(isosafe_frames_dropped_total[5m]) > rate(isosafe_frames_processed_total[5m])` |
| Slow inference | `histogram_quantile(0.95, rate(isosafe_inference_latency_seconds_bucket[5m])) > 0.5` |
| Alert latency | `histogram_quantile(0.95, rate(isosafe_alert_dispatch_latency_seconds_bucket[5m])) > 1` |
| No detections written | `rate(isosafe_detections_written_total[10m]) == 0` |

### Logs

Both Python services log **JSON to stdout**
([backend/app/logging_config.py](../backend/app/logging_config.py)):

```json
{"ts": "2026-10-07 10:13:32,345", "level": "WARNING", "logger": "app.ingestion.streams", "message": "stream ended, reconnecting in 4s", "request_id": null, "camera_id": "cam-3f9a12c0"}
```

`request_id` correlates API logs with the `x-request-id` response header;
`camera_id` is set on pipeline log lines about a camera. Ship them with any
Docker log driver. Uvicorn access logs are suppressed (WARNING level); nginx keeps
its own access log.

## Backups

The `backup` service runs [deploy/backup.sh](../deploy/backup.sh): it sleeps until
02:30 UTC, runs `pg_dump -Fc` to `deploy/backups/isosafe_<YYYYMMDD_HHMMSS>.dump`
on the host, and deletes dumps older than 14 days.

- The script computes the next run with GNU `date -d "tomorrow 02:30"`, falling
  back to BSD `date -v`. If the image's `date` supports neither, the script exits
  under `set -e` and the container restart-loops without producing backups (the
  PRD lists this as a known issue). Check with
  `docker compose logs backup` — a healthy service logs
  `backup: sleeping <N>s until next run`.
- Dumps contain the database only. **The `media` volume (snapshots, uploads,
  heatmaps) is not backed up.** Back it up separately if snapshot evidence matters.
- Copy `deploy/backups/` off the node; a backup on the same disk doesn't protect
  against disk loss.
- Also keep a safe copy of `.env` — without the same `FERNET_KEY`, restored
  camera sources can't be decrypted.

Manual backup at any time:

```bash
docker compose exec postgres pg_dump -U isosafe -Fc -f /backups/manual_$(date +%Y%m%d_%H%M).dump isosafe
```

Restore: follow [deploy/RESTORE.md](../deploy/RESTORE.md) (stop `backend` and
`inference`, recreate the DB, `timescaledb_pre_restore()`, `pg_restore`,
`timescaledb_post_restore()`, start, verify `/api/health`).

## Routine maintenance

| Task | Frequency |
|---|---|
| Verify a recent dump exists in `deploy/backups/` and copy it off-node | daily (automate) |
| Check disk usage of `pgdata` and `media` volumes | weekly |
| Review Admin → System Health for cameras with many reconnects | weekly |
| Prune heatmap archives (`media/heatmaps/*_<date>.json`) and old uploads | monthly |
| Test a restore on a spare machine | quarterly |
| Rotate the bootstrap/admin passwords and review users | quarterly |
| Rebuild images for OS and library security updates | monthly |

## Troubleshooting

| Symptom | Likely cause | What to check / do |
|---|---|---|
| Camera tile says **Offline** | Pipeline can't read the source | `docker compose logs inference | grep <camera_id>`; test the RTSP URL with `ffprobe` from the inference container; check credentials and that the camera is reachable from the Docker network |
| Camera never starts, log says `cannot decrypt source` | `FERNET_KEY` changed or missing | Restore the original key or re-enter the source |
| New camera doesn't appear for > 15 s | Inference container down or at `MAX_CAMERAS_PER_NODE` | `docker compose ps`; look for `MAX_CAMERAS_PER_NODE reached` |
| Live video but no boxes on the tile | Normal for `file` sources; on others, most frames are un-annotated previews | See [Pipeline › Dashboard frames](pipeline.md#dashboard-frames) |
| Edited source/URL has no effect | Only zones/rules hot-reload | Disable the camera, wait 15 s, re-enable; or restart `inference` |
| No incidents fire | No rules, schedule inactive (UTC!), cooldown, zone mismatch | Check camera rules; remember schedules use container time (UTC); verify zone ids match `zone_id` |
| Too many `zone_intrusion` alerts after applying a profile | `restricted` zone not drawn → rule covers whole frame | Draw the zone or remove the rule |
| `line_crossing` never fires | Zone isn't a line, or id mismatch | Draw a **Perimeter line** named exactly as the rule's `zone_id` |
| Analytics charts empty | Hourly upsert failing | `docker compose logs inference | grep "hourly aggregation failed"`; see [Known issues](known-issues.md#hourly-analytics-upsert) |
| Dashboard KPIs say 0 but detections exist | Same as above (KPIs come from `analytics_hourly`) | |
| AI Assistant disabled | No `ANTHROPIC_API_KEY` on `backend` | Set it, `docker compose up -d backend` |
| Search returns 422 "Forbidden keyword" | Validator matched a keyword in the generated SQL | Rephrase the question |
| Login returns 429 for everyone | Node-wide rate limit (shared nginx IP) | Wait 60 s; fix per [Security › Rate limiting](security.md#rate-limiting) |
| WebSocket keeps reconnecting | Expired token or nginx timeout | Check browser console; nginx WS timeout is 3600 s |
| `inference` restarts repeatedly | Memory guard or a crash | Logs for `exceeds limit`; lower workers/batch size or raise `WORKER_MEMORY_LIMIT_MB` |
| ONVIF discovery finds nothing | Multicast doesn't cross the Docker bridge | Use the camera's RTSP URL directly or run discovery from a host-networked container |
| Forgot admin password | | `docker compose exec backend python -m scripts.reset_admin <email> <new password>` (always pass a password; the script's default is `admin123`) |
| Upload "processing" forever | Upload jobs are never marked done | See [Known issues](known-issues.md#uploads-are-re-processed-and-never-complete) |

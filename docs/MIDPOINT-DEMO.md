# Midpoint Demo (end of Day 5)

Local, single-machine demo of the full agent chain:

```
Camera ─► Agent ─► Cloud API ─► Postgres + Redis + MinIO ─► Dashboard
```

The same `docker-compose.yml` runs both roles. The **agent** is the `inference`
service with `AGENT_MODE=1`; the **cloud** is `backend` (+ `postgres`, `redis`,
`minio`, `frontend`, `nginx`).

## 0. Bring the stack up

```bash
cp .env.example .env            # set AGENT_TOKEN + JWT_SECRET at minimum
docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d --build
docker compose ps               # backend / postgres / redis / minio / frontend healthy
```

Cloud API: <http://localhost:8000> (docs at `/docs`). Dashboard: <http://localhost:5173>
(or via nginx on <https://localhost>). MinIO console: <http://localhost:9001>.

Run the on-site agent (points the inference service at the cloud):

```bash
cloud_ip=localhost            # the box running the cloud stack
AGENT_MODE=1 CLOUD_URL=http://$cloud_ip:8000 AGENT_TOKEN=$AGENT_TOKEN \
  python -m app.pipeline.runner     # from backend/, inside the venv/container
```

Sanity check the agent handshake before demoing:

```bash
curl -s -H "Authorization: Bearer $AGENT_TOKEN" http://$cloud_ip:8000/agent/v1/config | jq .
curl -s http://$cloud_ip:8000/api/health | jq .agent      # {"online": true, ...}
```

## 1. Camera creation

Dashboard → **Cameras** → **Add camera** (RTSP URL or file loop). Or:

```bash
curl -s -X POST http://localhost:8000/api/cameras \
  -H "Authorization: Bearer $OPERATOR_JWT" -H 'Content-Type: application/json' \
  -d '{"name":"Demo cam","source":"rtsp://...","type":"rtsp","enabled":true}' | jq .
```

## 2. Agent receives camera

In agent mode the pipeline reconciles against the cloud, not a local DB:
`Pipeline._camera_rows()` calls `AgentClient.get_config()` → `GET /agent/v1/config`
every 15 s and starts/stops streams to match. The cloud returns the **decrypted**
source over the authenticated agent channel so the site box can open the stream.

The new camera appears in the agent log within one refresh cycle:

```
agent config version=<hash> cameras=1
camera stream started camera_id=cam-...
```

If the cloud is unreachable the fetch is skipped and the already-running cameras
keep streaming — a control-plane outage never drops the live view.

## 3. Live video

Dashboard → camera tile shows **LIVE** with the frame stream.

```bash
# frames flow agent -> WSS /agent/v1/stream -> cloud -> Redis FRAME_CHANNEL -> browser
redis-cli -h localhost -p 6379 subscribe isosafe:frames   # one JSON frame per tick
```

Frames are capped at 960 px and `AGENT_LIVE_FPS=2` (default).

## 4. Rule

Dashboard → **Rules** (zone editor) → add e.g. `loitering` with a zone and
threshold. The rule is part of the camera config the agent pulls.

> **Final acceptance (PRD v2 §8 step 4) needs an incident within 2 s of walking
> into the zone.** The Loitering rule defaults to `threshold_seconds: 30`, so the
> operator must set the threshold to ~2 in the rule editor before the walk (the
> engine fires once the track has been in-zone for `threshold_seconds`,
> `backend/app/rules/engine.py:148`).

## 5. Incident

When the rule fires, the agent POSTs `POST /agent/v1/incidents` (agent-owned
UUID) and uploads the annotated JPEG to the presigned S3 PUT.

```bash
redis-cli -h localhost -p 6379 subscribe isosafe:alerts | head    # incident alert
curl -s -H "Authorization: Bearer $OPERATOR_JWT" \
  http://localhost:8000/api/incidents | jq '.[0]'
```

## 6. Snapshot

The incident's `snapshot_url` is a **5-minute presigned S3 GET** resolved against
MinIO:

```bash
URL=$(curl -s -H "Authorization: Bearer $OPERATOR_JWT" \
  http://localhost:8000/api/incidents | jq -r '.[0].snapshot_url')
curl -s -o /dev/null -w '%{http_code}\n' "$URL"      # 200 immediately
sleep 301
curl -s -o /dev/null -w '%{http_code}\n' "$URL"      # 403 after expiry
curl -s -o /dev/null -w '%{http_code}\n' \
  http://localhost:8000/media/snapshots/leak.jpg     # 404 on staging (agent mode)
```

## 7. Acknowledge

Dashboard → **Incidents** → set status to `investigating`.

```bash
curl -s -X PATCH http://localhost:8000/api/incidents/1 \
  -H "Authorization: Bearer $OPERATOR_JWT" -H 'Content-Type: application/json' \
  -d '{"status":"investigating"}' | jq .status
```

## 8. Resolve

Transition to `resolved` (sets `resolved_at`):

```bash
curl -s -X PATCH http://localhost:8000/api/incidents/1 \
  -H "Authorization: Bearer $OPERATOR_JWT" -H 'Content-Type: application/json' \
  -d '{"status":"resolved","resolution_notes":"Verified by guard"}' | jq .status
```

## 9. Agent health

Dashboard → **Admin** → *System Health* shows the **Agent** card (online,
version, last-seen, CPU/mem/disk) and the per-camera health table.

```bash
curl -s http://localhost:8000/api/health | jq .agent
# {"online": true, "agent_version": "1.0-agent", "last_seen_ago": 3.2,
#  "cpu": 41.2, "mem": 63.0, "disk_free_gb": 120, "cameras": [...]}
```

Online window is `AGENT_ONLINE_SECS=90`.

## Automated checks

```bash
cd backend
PYTHONPATH=. python -m pytest tests/test_agent_api.py tests/test_agent_outbox.py \
  tests/test_agent_snapshots.py tests/test_agent_stream.py -q   # security + core
python -m scripts.smoke_api http://localhost:8000               # REST smoke
```

The snapshot-expiry check runs for real against MinIO (open now -> 200, after the
window -> 403) whenever an S3 endpoint is configured; it skips otherwise:

```bash
S3_BUCKET=isosafe-snapshots S3_ENDPOINT_URL=http://localhost:19000 \
  S3_PUBLIC_ENDPOINT_URL=http://localhost:19000 S3_ACCESS_KEY=minioadmin \
  S3_SECRET_KEY=minioadmin python -m pytest tests/test_agent_snapshots.py -q
```

## Resiliency spot-check (outage)

1. Stop the cloud: `docker compose stop backend`.
2. Trigger a rule; incidents accumulate in the agent outbox (max 500, ~5 min).
3. Restart: `docker compose start backend`.
4. Incidents post automatically; the cloud-upsert by UUID means **no duplicates**
   even if a response was lost (`duplicate: true` on replay).

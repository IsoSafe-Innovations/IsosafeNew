# API Reference

Base path `/api`. All bodies are JSON unless noted. Timestamps are ISO 8601; send
them with a timezone (`2026-10-07T00:00:00Z`) — naive values are compared against
UTC `timestamptz` columns and may be interpreted in the server's zone.

Every response carries an `x-request-id` header (taken from the request header of
the same name if present, else generated); the same id appears as `request_id`
in the backend's JSON logs.

## Authentication

Send the access token as `Authorization: Bearer <access_token>`.

| Minimum role | Meaning |
|---|---|
| public | no token |
| viewer | any signed-in user |
| operator | `operator` or `admin` |
| admin | `admin` only |

Errors: **401** missing/invalid/expired token, **403** role too low
(`{"detail": "Requires admin role"}`), **429** rate limit exceeded. Validation
errors are **422** with FastAPI's standard `detail` array or a string.

### Endpoint index

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/api/auth/login` | public | Get tokens |
| POST | `/api/auth/refresh` | public | Rotate tokens |
| GET | `/api/users` | admin | List users |
| POST | `/api/users` | admin | Create user |
| PATCH | `/api/users/{id}` | admin | Change role/password |
| DELETE | `/api/users/{id}` | admin | Delete user |
| GET | `/api/cameras` | viewer | List cameras with live health |
| POST | `/api/cameras` | admin | Create camera |
| PATCH | `/api/cameras/{id}` | admin | Update camera |
| DELETE | `/api/cameras/{id}` | admin | Delete camera |
| GET | `/api/cameras/profiles` | viewer | List vertical profiles |
| POST | `/api/cameras/discover` | admin | ONVIF WS-Discovery scan |
| POST | `/api/cameras/discover/stream-uri` | admin | Resolve an ONVIF device's RTSP URI |
| GET | `/api/detections` | viewer | Query detections (cursor-paginated) |
| GET | `/api/incidents` | viewer | List incidents |
| GET | `/api/incidents/{id}` | viewer | Get incident |
| PATCH | `/api/incidents/{id}` | operator | Update status/assignment/notes |
| GET | `/api/stats/{camera_id}` | viewer | Hourly analytics series |
| GET | `/api/counts` | viewer | Live per-camera counts |
| GET | `/api/heatmap/{camera_id}` | viewer | Latest heatmap grid |
| GET | `/api/overview` | viewer | Dashboard KPIs |
| POST | `/api/uploads` | operator | Upload footage |
| GET | `/api/uploads/{job_id}` | operator | Upload job status |
| POST | `/api/search` | viewer | Natural-language search |
| GET | `/api/insights` | viewer | Cached AI insights |
| POST | `/api/insights/refresh` | viewer | Regenerate AI insights |
| GET | `/api/reports/{type}` | viewer | PDF/XLSX report |
| GET | `/api/health` | public | DB + Redis health |
| GET | `/api/metrics` | public | Prometheus metrics |
| WS | `/api/ws?token=…` | viewer | Live frames, counts, incidents |
| GET | `/media/...` | public (nginx) | Snapshots, heatmap files, uploads |

---

## Auth

### `POST /api/auth/login`

Rate limit: 10 / minute per client IP.

```json
{"email": "admin@isosafe.local", "password": "…"}
```

**200**

```json
{
  "access_token": "eyJ…",
  "refresh_token": "eyJ…",
  "role": "admin",
  "email": "admin@isosafe.local"
}
```

**401** `Invalid credentials`. Email is lowercased and must look like
`x@y.z` (internal TLDs such as `.local` are allowed).

### `POST /api/auth/refresh`

Rate limit: 30 / minute per client IP.

```json
{"refresh_token": "eyJ…"}
```

Returns the same shape as login with **new** access and refresh tokens. The
user's current role is re-read from the database, so role changes take effect at
the next refresh. **401** if the token is invalid/expired, is an access token, or
the user was deleted.

Tokens are HS256 JWTs with claims `sub` (email), `role`, `type`
(`access`/`refresh`), `jti`, `iat`, `exp`. Old refresh tokens are not revoked
when a new pair is issued.

---

## Users (admin)

### `GET /api/users`

```json
[{"id": "5b0c…", "email": "ops@acme.lan", "role": "operator", "created_at": "2026-10-01T09:12:44+00:00"}]
```

### `POST /api/users` → 201

```json
{"email": "ops@acme.lan", "password": "at-least-8-chars", "role": "operator"}
```

**422** bad role or password shorter than 8; **409** email exists.

### `PATCH /api/users/{id}`

Any of `{"role": "...", "password": "..."}`. **404** unknown id, **422** nothing
to update. Returns `{id, email, role}`.

### `DELETE /api/users/{id}` → 204

There is no guard against deleting or demoting the last admin, or yourself.
Existing access tokens of a deleted user stay valid until they expire (≤ 30 min);
refresh fails immediately.

---

## Cameras

### Camera object

```json
{
  "id": "cam-3f9a12c0",
  "name": "Loading dock",
  "source": "rtsp://***@10.0.0.21:554/stream1",
  "type": "rtsp",
  "vertical_profile": "warehouse",
  "zones": [{"id": "gate", "name": "gate", "polygon": [[0.1, 0.5], [0.6, 0.5], [0.6, 0.95], [0.1, 0.95]]}],
  "rules": [{"id": "wh-dock-vehicle", "type": "stopped_vehicle", "zone_id": "gate", "threshold_seconds": 900, "severity": "info", "cooldown_seconds": 1800}],
  "refresh_secs": 2.0,
  "loop_file": true,
  "enabled": true,
  "created_at": "2026-10-01T09:30:00+00:00",
  "health": {"online": true, "fps": 8.3, "reconnect_count": 0, "frames_dropped": 12, "last_frame_ts": 1759832000.4}
}
```

`source` is always **redacted** in responses: credentials in `scheme://user:pass@host`
become `***`; if it can't be decrypted it shows `<encrypted>`. `health` is
present only in the list response.

### `GET /api/cameras` (viewer)

All cameras, with `health` from Redis. A camera is `online` if a frame was
enqueued in the last 30 s; cameras with no health key report
`{"online": false, "fps": 0, "reconnect_count": 0, "frames_dropped": 0}`.

### `POST /api/cameras` (admin) → 201

| Field | Type | Default | Notes |
|---|---|---|---|
| `name` | string | required | |
| `source` | string | required | encrypted at rest |
| `type` | string | required | `rtsp`, `snapshot_url`, `file` |
| `vertical_profile` | string \| null | null | if set **and** `rules` is empty, the profile's rules are copied in |
| `zones` | array | `[]` | |
| `rules` | array | `[]` | not schema-validated beyond being a list of objects |
| `refresh_secs` | number | 2.0 | snapshot polling interval |
| `loop_file` | bool | true | |
| `enabled` | bool | true | |

**422** bad type; **409** `MAX_CAMERAS_PER_NODE reached`. Audited as
`camera.create`.

### `PATCH /api/cameras/{id}` (admin)

Any subset of the create fields. Only sent fields change. Zones and rules
replace the whole array. Changes to `zones`/`rules`/`enabled` reach the pipeline
within 15 s; see [Pipeline › Camera reconciliation](pipeline.md#camera-reconciliation)
for which fields require a stream restart. **404**, **422**. Audited with
`source` masked.

### `DELETE /api/cameras/{id}` (admin) → 204

Stops the stream within 15 s. Detections, incidents and analytics for the camera
are kept.

### `GET /api/cameras/profiles` (viewer)

```json
[{"id": "retail", "label": "Retail Store", "kpi_cards": ["people_today", "..."], "default_reports": ["daily_summary", "weekly_security"], "rule_count": 3}]
```

### `POST /api/cameras/discover` (admin)

WS-Discovery multicast scan (5 s) from the **backend container's network**. Returns ONVIF candidates; nothing is added automatically.

```json
[{"host": "10.0.0.31", "port": 80, "xaddr": "http://10.0.0.31/onvif/device_service", "scopes": ["onvif://www.onvif.org/name/IPC"]}]
```

Multicast does not cross Docker's default bridge network, so in a standard
Compose deployment this usually returns `[]`. Run the backend with
`network_mode: host` or discover from a host-networked tool. Errors return `[]`.

### `POST /api/cameras/discover/stream-uri` (admin)

```json
{"host": "10.0.0.31", "port": 80, "username": "admin", "password": "…"}
```

**200** `{"stream_uri": "rtsp://admin:…@10.0.0.31:554/Streaming/Channels/101"}`
— credentials are embedded for OpenCV. **502** if the device can't be queried.
Use this URI as the camera `source`.

---

## Detections

### `GET /api/detections` (viewer)

| Query | Notes |
|---|---|
| `camera` | camera id |
| `from`, `to` | inclusive timestamp bounds |
| `type` | object type |
| `plate` | case-insensitive substring of `plate_text` (input uppercased) |
| `limit` | 1–1000, default 100 |
| `cursor` | from the previous page's `next_cursor` |

Ordered newest first by `(ts, id)`. Pagination is keyset-based (never
`OFFSET`), so deep pages are as fast as the first.

```json
{
  "items": [
    {"id": 99812, "camera_id": "cam-3f9a12c0", "ts": "2026-10-07T10:13:31.902+00:00",
     "object_type": "car", "confidence": 0.81, "track_id": 412,
     "bbox": [0.10, 0.44, 0.33, 0.70], "zone_ids": ["gate"],
     "plate_text": "KJA123AB", "plate_confidence": 0.62}
  ],
  "next_cursor": "eyJ0cyI6ICIyMDI2LTEwLTA3VDEwOjEzOjMxLjkwMiswMDowMCIsICJpZCI6IDk5ODEyfQ=="
}
```

`next_cursor` is `null` on the last page. **422** for an invalid cursor.
Without filters on a large table this scans recent chunks only, but always pass
`camera` and a time range for investigations.

---

## Incidents

### Incident object

```json
{
  "id": 1842, "camera_id": "cam-3f9a12c0", "ts": "2026-10-07T10:13:32.345+00:00",
  "incident_type": "loitering", "severity": "warning",
  "description": "Person loitering for 34s in zone 'entrance'",
  "snapshot_path": "snapshots/2026-10-07/cam-3f9a12c0_1759832012345_loitering.jpg",
  "snapshot_url": "/media/snapshots/2026-10-07/cam-3f9a12c0_1759832012345_loitering.jpg",
  "clip_path": null, "status": "open", "assigned_to": null,
  "resolved_at": null, "resolution_notes": null
}
```

### `GET /api/incidents` (viewer)

Filters: `status`, `severity`, `camera`, `incident_type`, `from`, `to`;
`limit` 1–500 (default 100). Newest first. No pagination beyond `limit`; narrow
the time range for older data.

### `GET /api/incidents/{id}` (viewer)

**404** if unknown.

### `PATCH /api/incidents/{id}` (operator)

Any of:

```json
{"status": "investigating", "assigned_to": "ops@acme.lan", "resolution_notes": "Customer waiting for taxi"}
```

Status transitions are enforced (see
[Alerts and incidents › Lifecycle](alerts-and-incidents.md#incident-lifecycle)):
**409** `Cannot transition closed -> resolved`. **422** invalid status or empty
body. Returns the updated incident. Audited as `incident.update`.

---

## Stats and live data

### `GET /api/stats/{camera_id}?hours=24` (viewer)

`hours` 1–720. `camera_id` may be `all` to sum footfall/incidents and
average queue/occupancy across cameras per bucket (in that mode `vehicles` is
always `{}`).

```json
{"camera_id": "all", "hours": 24, "buckets": [
  {"bucket": "2026-10-07T09:00:00+00:00", "footfall": 132, "vehicles": {}, "avg_queue": 2.4,
   "max_queue": 7, "avg_occupancy": 5.1, "incident_count": 3}
]}
```

### `GET /api/counts` (viewer)

Live counts straight from Redis, refreshed ≤ 1/s per camera by the pipeline.

```json
{"cam-3f9a12c0": {"in_frame": {"person": 3, "car": 1}, "session": {"person": 418, "car": 57}, "ts": 1759832012.3}}
```

`session` = unique tracks since the pipeline started.

### `GET /api/heatmap/{camera_id}` (viewer)

Contents of `heatmaps/<camera_id>_latest.json` —
`{"camera_id", "hour", "grid": [[...32 ints] x 32]}`. **404** if none yet.

### `GET /api/overview` (viewer)

```json
{
  "today":     {"footfall": 1204, "avg_occupancy": 6.3, "incidents": 14, "vehicles": 233},
  "yesterday": {"footfall": 2410, "avg_occupancy": 5.8, "incidents": 22, "vehicles": 498},
  "open_incidents": 5,
  "suspicious_today": 9
}
```

Days are UTC.

---

## Uploads

### `POST /api/uploads` (operator) → 202

`multipart/form-data` with field `file`. Extensions: `.mp4 .avi .mov .mkv .webm`.
Max `UPLOAD_MAX_MB` (500); nginx allows bodies up to 512 MB.

```json
{"job_id": "0f3c5d7e-…", "camera_id": "upload-0f3c5d7e", "status": "processing"}
```

**422** unsupported extension; **413** too large. The file becomes a single-pass
`file` camera picked up within 15 s.

### `GET /api/uploads/{job_id}` (operator)

```json
{"id": "0f3c5d7e-…", "filename": "lobby.mp4", "camera_id": "upload-0f3c5d7e",
 "status": "processing", "error": null, "created_at": "…", "completed_at": null}
```

---

## AI

### `POST /api/search` (viewer)

Rate limit: 20 / minute per client IP.

```json
{"query": "Which camera had the most loitering alerts this week?"}
```

**200**

```json
{
  "sql": "SELECT camera_id, COUNT(*) AS alerts FROM incidents WHERE incident_type = 'loitering' AND ts >= now() - interval '7 days' GROUP BY camera_id ORDER BY alerts DESC LIMIT 10",
  "explanation": "Counts loitering incidents per camera over the last 7 days.",
  "columns": ["camera_id", "alerts"],
  "rows": [["cam-3f9a12c0", 41], ["cam-8812aa01", 12]],
  "row_count": 2
}
```

**422** empty query / model returned invalid JSON / SQL rejected
(`Generated SQL rejected: Forbidden keyword: LOCK`); **503** not configured;
**500** execution failure (including the 5 s timeout).

### `GET /api/insights` (viewer)

```json
{"available": true, "generated_at": "2026-10-07T10:00:03+00:00",
 "insights": [{"title": "…", "detail": "…", "kind": "staffing"}]}
```

`{"available": false, "insights": [], "generated_at": null}` without an API key.

### `POST /api/insights/refresh` (viewer)

Rate limit: 4 / hour per client IP. Calls the model synchronously and returns
the new cached payload. **503** without an API key.

---

## Reports

### `GET /api/reports/{report_type}` (viewer)

| Query | Default |
|---|---|
| `format` | `pdf` (`pdf` or `xlsx`) |
| `from` | `to` minus the report's default period |
| `to` | now |

`report_type`: `daily_summary`, `weekly_security`, `monthly_business`,
`incident_report`, `camera_health`. Streams a file with
`Content-Disposition: attachment; filename="isosafe_<type>_<YYYYMMDD>.<ext>"`.
**404** unknown type. Contents: [Analytics › Reports](analytics-and-ai.md#reports).

---

## Health and metrics

### `GET /api/health` (public)

```json
{"status": "ok", "database": {"ok": true, "error": null}, "redis": {"ok": true, "error": null}}
```

`status` is `degraded` if either check fails; the HTTP status is 200 either way.
This checks the API's dependencies only — not the pipeline. Use
`GET /api/cameras` health or the inference container's status for that.

### `GET /api/metrics` (public)

Prometheus text format from the API process (see
[Operations › Monitoring](operations.md#monitoring)).

---

## WebSocket `/api/ws`

```
wss://<host>/api/ws?token=<access_token>
```

The token is validated once at connect. An invalid or expired token gets the
socket accepted then closed with code **4401**. An established connection is not
closed when its token later expires; the frontend reconnects with a fresh token
whenever it refreshes.

### Client → server

```json
{"action": "subscribe",   "camera_ids": ["cam-3f9a12c0"]}
{"action": "unsubscribe", "camera_ids": ["cam-3f9a12c0"]}
{"action": "set",         "camera_ids": ["cam-3f9a12c0", "cam-8812aa01"]}
```

`set` replaces the subscription set. Invalid JSON and unknown actions are
ignored. Subscriptions are per connection and lost on reconnect, so re-send
`set` after reconnecting.

### Server → client

**`frame`** — only for cameras this connection subscribed to:

```json
{"type": "frame", "camera_id": "cam-3f9a12c0", "image": "<base64 JPEG>",
 "counts": {"person": 418}, "in_frame": {"person": 3}, "ts": 1759832012.3}
```

**`counts`** — for every camera the connection did *not* subscribe to, derived
from the same frame publications (no image):

```json
{"type": "counts", "camera_id": "cam-8812aa01", "counts": {"car": 57}, "in_frame": {"car": 1}, "ts": 1759832012.4}
```

**`incident`** — every alert, to every client:

```json
{"type": "incident", "id": 1842, "camera_id": "cam-3f9a12c0", "incident_type": "loitering",
 "severity": "warning", "description": "…", "snapshot_url": "/media/…", "ts": "2026-10-07T10:13:32.345+00:00"}
```

System self-alerts arrive as `incident` messages with `camera_id: "system"`,
`incident_type: "system_health"`, and no `id`.

Each client has a 30-message send queue; when a slow client falls behind, its
oldest queued messages are dropped. Messages are not replayed after a
disconnect.

### Minimal client

```javascript
const ws = new WebSocket(`wss://${location.host}/api/ws?token=${accessToken}`);
ws.onopen = () => ws.send(JSON.stringify({ action: 'set', camera_ids: ['cam-3f9a12c0'] }));
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'frame') img.src = `data:image/jpeg;base64,${msg.image}`;
  if (msg.type === 'incident') console.log('ALERT', msg.severity, msg.description);
};
```

---

## Media files

nginx serves the media volume read-only at `/media/` (1 h cache), and the API
also mounts it at `/media` when the directory exists (used in development
through Vite's proxy):

| Path | Contents |
|---|---|
| `/media/snapshots/<date>/<file>.jpg` | incident snapshots |
| `/media/heatmaps/<camera>_<hour>.json` | heatmap archives |
| `/media/uploads/<job_id>.<ext>` | uploaded footage |

These URLs require **no authentication**. See [Security](security.md#media-files).

## Rate limiting details

Fixed-window counters in Redis (`INCR` + `EXPIRE` on first hit), keyed by
endpoint and `request.client.host`. Behind the bundled nginx, the client host
seen by the API is the nginx container, so in practice the limits are **shared by
all users** of a node (see [Known issues](known-issues.md#rate-limits-are-global-behind-nginx)).

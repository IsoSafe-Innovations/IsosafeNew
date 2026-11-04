# Development

Setup instructions are in [Getting started › Local development](getting-started.md#local-development).
This page covers conventions, testing, the harness scripts, and recipes for
extending the system.

## Conventions

- **Python 3.11+, asyncio throughout.** Anything blocking (OpenCV reads, EasyOCR,
  SMTP, ONVIF) goes through `loop.run_in_executor`. CPU-heavy model inference
  goes through the process pool.
- **SQLAlchemy Core**, not the ORM. Tables in `app/db/tables.py`; queries are
  `sa.select/insert/update` or `sa.text` for complex SQL. High-volume inserts use
  the raw asyncpg pool.
- **Settings** only through `get_settings()`; add new tunables to `Settings` with
  an `alias` matching the env var, a safe default, and an entry in
  `.env.example` and [Configuration](configuration.md).
- **Schema changes** only through Alembic, mirrored in `tables.py`.
- **Admin/operator mutations** call `write_audit(...)`.
- **Never return camera sources unredacted**; serialize through `_serialize` in
  `api/cameras.py`.
- **Logging:** `log = logging.getLogger(__name__)`; pass
  `extra={"camera_id": ...}` for per-camera messages so they're filterable.
- **Normalized coordinates** (0..1) for anything geometric.
- Frontend: function components and hooks, Tailwind classes, the shared `api`
  helpers, no extra state libraries.

## Tests

```bash
cd backend
python -m pytest tests
```

`pytest.ini` sets `asyncio_mode = auto`, and `tests/conftest.py` puts `backend/`
on `sys.path`. The suite is pure unit tests — no database, Redis, model, or
network — and runs in seconds.

| File | Covers |
|---|---|
| `test_rule_engine.py` | Every rule type, cooldown fire-once and expiry, zone exit reset, schedule windows (overnight, day filter), unknown types ignored |
| `test_tracker.py` | Track continuity, new tracks beyond the gate, class gating, expiry, history cap, greedy matching |
| `test_zones.py` | Point-in-polygon, degenerate polygons, `zones_containing`, line crossing |
| `test_sql_validator.py` | Valid SELECT/CTE queries pass; injection attempts (stacked queries, comments, DDL/DML, catalogs, disallowed tables) are rejected |
| `test_security.py` | bcrypt round-trip, JWT round-trip and type enforcement, tampering, Fernet source encryption, no-key passthrough |
| `test_profiles.py` | All 14 profiles exist, only known rule types, deep copies, estate contents, unknown profile |
| `test_streams.py` | Drop-oldest queue behaviour, unknown source type, stop terminates the loop |

The rule-engine tests show the pattern for driving the engine deterministically:
feed a `CentroidTracker` synthetic detections with explicit timestamps and call
`engine.evaluate(tracks, now=...)`.

There are no frontend tests and no API tests in pytest; API behaviour is covered
by the smoke harness below.

## Harness scripts

Run from `backend/` with the environment pointing at a real database/Redis.

| Script | Purpose | Needs |
|---|---|---|
| `python -m scripts.smoke_api <base_url>` | ~40 end-to-end API checks: health, metrics, OpenAPI, login/refresh, 401/403 matrix for a viewer, camera CRUD with profile + redaction, zones, detections cursor pagination, incidents, stats, overview, counts, search/insights degradation without a key, PDF/XLSX reports, profiles | Running API; an admin `admin@isosafe.local` / `smoke-test-pass1`; benchmark data for `cam-05` (run `bench_detections` first); **no** `ANTHROPIC_API_KEY` |
| `python -m scripts.bench_detections` | Inserts 1,000,000 synthetic detections over 7 days for 16 cameras and times a 24 h hourly-grouped query against a <100 ms target | DB. Leaves the rows in place — use a scratch database |
| `python -m scripts.pipeline_e2e --video ../sample_videos/vtest.avi --seconds 90` | Runs the real pipeline in-process on a looping file camera with an 8 s loitering rule and verifies detections written, ≥3 person tracks, an incident with a snapshot on disk, cooldown spacing, frames published to Redis, and camera health | DB, Redis, YOLO weights, writable `MEDIA_ROOT`. Don't run while the `inference` container is up |
| `python -m scripts.load_test --password … --cameras 64 --ws-clients 20 --rps 50 --minutes 240` | Soak test: creates N looping file cameras, opens W WebSocket clients (4 cameras each), drives R req/s against read endpoints, reports p50/p95/p99 latency, WS message counts, and alert latency p95 against <1 s | Running stack with inference; `websockets` package (not in requirements) |
| `python -m scripts.reset_admin <email> <password>` | Reset a user's password | DB. Defaults to `admin@isosafe.local` / `admin123` if arguments are omitted |

Inside Docker, run them with `docker compose exec backend python -m scripts.<name> ...`.

## Recipes

### Adding a rule type

1. **Engine** — in [backend/app/rules/engine.py](../backend/app/rules/engine.py):
   - add the type name to `RULE_TYPES`;
   - add a method `_eval_<type>(self, rule, rule_id, tracks, now, settings)` that
     returns a `RuleFire(rule_id, incident_type, severity, description, track_or_None)`
     or `None`. Per-track state goes in `track.rule_state[rule_id]`. Use
     `self._in_zone(track, rule.get("zone_id"))` for zone filtering.
   The dispatcher finds the handler by name; schedule and cooldown are handled
   for you.
2. **Tests** — add cases to `tests/test_rule_engine.py` using `run_frames`.
3. **UI** — add a template to `RULE_TEMPLATES` in
   [frontend/src/views/Cameras.jsx](../frontend/src/views/Cameras.jsx).
4. **Profiles** (optional) — reference it in `profiles/registry.py`;
   `test_all_profile_rules_use_known_types` will check it.
5. **Docs** — add it to [Rules, zones and profiles](rules-and-zones.md).

No migration is needed: the new type is stored in the existing JSONB, and
`incident_type` is free text.

### Adding a detected object class

1. Add the COCO id → name to `KEEP_CLASSES` in
   [backend/app/inference/worker.py](../backend/app/inference/worker.py). Decide
   which threshold it uses (the worker uses `PERSON_CONFIDENCE` for `person` and
   `VEHICLE_CONFIDENCE` for everything else).
2. If it's a vehicle or bag, add it to `VEHICLE_TYPES` / `BAG_TYPES` in both
   `worker.py` and `rules/engine.py` (they're duplicated).
3. Update the analytics SQL in `analytics/jobs.py` if it should be counted, the
   `SCHEMA_DDL` comment in `search/nl_search.py`, and `OBJECT_TYPES` in
   `frontend/src/views/Investigations.jsx`.

To use a custom-trained model, set `YOLO_MODEL` to its path and change
`KEEP_CLASSES` to its class ids.

### Adding a vertical profile

Add an entry to `PROFILES` in
[backend/app/profiles/registry.py](../backend/app/profiles/registry.py) with
`label`, `kpi_cards`, `default_reports`, and `rules`. Prefer the well-known zone
ids. Update `test_all_verticals_present` and the profile table in the docs.

### Adding an API endpoint

1. Create or extend a router in `backend/app/api/`; protect it with
   `Depends(require_viewer | require_operator | require_admin)`.
2. For new routers, include them in the loop in `app/main.py`.
3. Keep the `/api/...` prefix so nginx routes it.
4. Audit mutations with `write_audit`. Add `dependencies=[Depends(rate_limited(...))]`
   for expensive or abuse-prone endpoints.
5. Add a smoke check in `scripts/smoke_api.py` and document it in the
   [API reference](api-reference.md).

### Adding a report

Add the id/label to `REPORT_TYPES` and a default period in `generate_report`;
add a branch in `_build_pdf` (and `_build_xlsx` if it needs a different sheet);
add a card to `REPORTS` in `frontend/src/views/Reports.jsx`.

### Adding an alert channel

Write `async def _dispatch_<channel>(alert: dict)` in
[backend/app/alerts/dispatcher.py](../backend/app/alerts/dispatcher.py), guard it
on its settings, never let it raise, and add it to the `asyncio.gather` in
`run_dispatcher`. Blocking clients go through `run_in_executor`.

### Adding a source type

Add a branch in `CameraStream.run()` that calls a new
`_run_<type>()` reader returning `True` if it delivered frames, use
`self._enqueue(image)` and `await self.health.record_frame()` per frame, and add
the type to `SOURCE_TYPES` in `api/cameras.py` and the Cameras form.

## Working on the frontend against Docker

Start the full stack, then publish the backend port so Vite can proxy to it:

```yaml
# docker-compose.override.yml
services:
  backend:
    ports: ["8000:8000"]
```

```bash
docker compose up -d
```

```bash
cd frontend && npm run dev
```

Add `http://localhost:5173` to `CORS_ORIGINS` if you call the API cross-origin
(the Vite proxy makes calls same-origin, so usually not needed).

## Git

`main` is the default branch. `.env`, model weights (`*.pt`), media, backups,
certificates, and sample videos (`sample_videos/*.mp4|avi|mov`) are git-ignored.

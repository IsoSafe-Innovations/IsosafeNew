# Iso Safe PRD: MVP v1.0 (Developer Edition)

**Sep 29, 2026 · @Fimber**

This is the **canonical spec for backend engineers**. It describes what the codebase does today, what must not regress, and **what is not built yet** (your backlog).

**Repo layout (backend):**

| Path | Responsibility |
|------|----------------|
| `backend/app/main.py` | FastAPI app, bootstrap admin, WS manager lifecycle |
| `backend/app/pipeline/runner.py` | Inference supervisor: reconcile cameras, inference loop |
| `backend/app/pipeline/camera_worker.py` | Per-frame: tracker, rules, OCR cadence, Redis frame publish |
| `backend/app/ingestion/streams.py` | RTSP / snapshot / file readers |
| `backend/app/inference/` | YOLO workers, OCR, tracker, detection writer |
| `backend/app/rules/engine.py` | Eight rule evaluators |
| `backend/app/analytics/jobs.py` | Hourly/daily rollups, heatmap snapshots |
| `backend/app/ws/` | WebSocket auth + Redis fanout |
| `backend/app/api/` | REST routes |
| `backend/tests/` | Unit tests (run: `python -m pytest tests` from `backend/`) |

---

## 0. Implementation status (read this first)

### 0.1 Shipped in MVP v1.0 (do not break)

- Full Docker stack: postgres (TimescaleDB), redis, backend, inference, frontend, nginx, prometheus, backup job
- JWT auth (viewer / operator / admin), bootstrap admin, user CRUD (admin)
- Cameras CRUD, 14 vertical profiles, zones + rules JSON, ~15s pipeline reconcile
- YOLOv8 + centroid tracking, 8 rule types, incidents + snapshots
- EasyOCR assistive LPR (global cadence), plate on detections + investigations search
- WebSocket live frames + incidents; optional SMTP/webhook
- Reports PDF/XLSX, investigations, detections API with cursor pagination
- Optional Anthropic Assistant + Insights
- Video **upload jobs** (`POST /api/uploads`) → file camera (operator+)

### 0.2 Known bugs / tech debt (fix, not optional for production hardening)

| Issue | Location | Symptom |
|-------|----------|---------|
| Hourly analytics upsert SQL | `backend/app/analytics/jobs.py` | `GroupingError: subquery uses ungrouped column "d.ts"` in logs; hourly buckets may not update |
| `plate_logging` profile flag | `profiles/registry.py` only | Estate profile sets `plate_logging: true` but pipeline **ignores** it; OCR runs for all vehicles globally |
| Estate profile KPIs | `unknown_vehicles`, `gate_congestion` | Listed on profile JSON only; **`/api/overview` does not expose them** (dashboard uses footfall, vehicles, suspicious_today, etc.) |
| Backup sidecar | `docker-compose.yml` `backup` service | May restart-loop in some environments; core app unaffected |
| WebSocket after token expiry | Frontend + `/api/ws` | Fixed in repo: reconnect + refresh; verify after deploy |

### 0.3 Not in the project yet (backend backlog — you will build)

Prioritized for **v1.1** unless product re-prioritizes:

| ID | Feature | Notes |
|----|---------|--------|
| MVP-FR-L08 | Per-camera LPR-first mode (OCR cadence, min crop) | DB/API + pipeline respect camera flags |
| MVP-FR-L07 | Enforce `plate_logging` on profile/camera | Skip or increase OCR only where configured |
| MVP-FR-L09 | Plate watchlist + incident on match | New table or Redis set; rule or post-OCR hook |
| MVP-FR-L10 | Unknown vehicle at gate (crossing + no plate) | Composite rule or incident type |
| MVP-FR-T10 | Traffic log report / CSV export | Dedicated endpoint or report type beyond raw `/api/detections` |
| MVP-FR-T09 | `queue_threshold` for **vehicles** | Extend rule engine + zone counts |
| MVP-FR-T08 | Traffic camera setup wizard | Mostly frontend + docs; backend preset endpoint optional |
| — | Wire estate KPIs `unknown_vehicles`, `gate_congestion` | Define metrics + add to `/api/overview` or profile-specific stats |
| — | Multi-tenancy, edge connector, SSO | **Out of MVP** — see §9 |

---

## 1. Overview

Iso Safe is an on-premises AI layer for existing CCTV. Each customer gets **one node**, hosted online or on-site, that ingests camera streams, detects and tracks people and vehicles, evaluates zone rules, and turns rule hits into incidents, live alerts, analytics and reports.

**MVP v1.0 core is built.** This document describes current behavior, hard constraints, and the gap list in §0.3.

| Attribute | MVP v1.0 value |
|-----------|----------------|
| Deployment | One Docker Compose stack per customer, hosted online (VPS + domain) or on-site |
| Tenancy | Single tenant: one organization per deployment |
| User access | Browser only at `https://<host>/`; no client install |
| Camera sources | RTSP, HTTP snapshot URL, video file |
| Capacity | Up to 64 cameras per node (`MAX_CAMERAS_PER_NODE`; hardware dependent) |
| Detection | YOLOv8 (person + vehicle), centroid tracking, EasyOCR plate reads (assistive LPR, §5.9) |
| Rule types | 8 |
| Roles | viewer, operator, admin |
| External dependency | Anthropic API optional, **text only** (no video) |

**How to read this doc:** §3 architecture, §5 requirements, §6 rules. §7 NFRs and env vars. §10 definition of done. §11 first-week checklist. **§0** = built vs backlog.

**Core product principles (hard constraints):**

- **Privacy by default.** Video, RTSP and DB contents stay inside the customer deployment.
- **Single tenant per deployment.** One stack, one org; users only need a browser.
- **Rules are data.** JSON on camera rows; pipeline picks up edits in ~15s, no restart.
- **Fast alert path.** Detection → rule → Redis → WebSocket; operators see alerts in-session.
- **Graceful degradation.** No `ANTHROPIC_API_KEY` → Assistant/Insights disabled; core features run.

---

## 2. Glossary

| Term | Meaning |
|------|---------|
| Node | One full Docker stack for one site/customer |
| Camera | DB row: source, zones, rules JSON |
| Vertical profile | Preset seeding default rules (retail, estate, …) |
| Zone | Polygon or line, normalized 0–1 coordinates |
| Detection | One object in one processed frame; optional `plate_text` |
| Track | Centroid tracker ID per camera |
| Rule | Condition on tracks/zones → incident when fired |
| Incident | Rule hit record + snapshot + workflow fields |
| Cooldown | Min time before same rule fires again |
| Rollup | Hourly/daily analytics buckets |
| Pipeline | `inference` container: ingest, YOLO, rules, writes |

---

## 3. System architecture

Pipeline container does all video work → Postgres, Redis, media store. API serves React via nginx.

**Optional external:** Anthropic (text). Email/webhook for incident metadata.

**Alert path**

1. Reader → bounded queue (drop-oldest).
2. Every `PROCESS_EVERY_N_FRAMES` → YOLO in process pool.
3. Tracker + zone tags → batch detection writes.
4. Rule engine → incident + snapshot → Redis publish.
5. API `_redis_pump` → WebSocket; optional email/webhook.

Pipeline **reconciles cameras ~every 15s** from DB.

**Tech stack**

| Layer | Choice |
|-------|--------|
| API | Python 3.11, FastAPI, Gunicorn + Uvicorn workers |
| Pipeline | asyncio + ProcessPoolExecutor, YOLOv8, EasyOCR |
| Database | PostgreSQL 16 + TimescaleDB, SQLAlchemy 2 async, asyncpg batch writer |
| Cache/pub/sub | Redis 7 |
| Frontend | React (Vite), nginx static + reverse proxy |
| Auth | JWT, bcrypt |
| Observability | Prometheus, structured logs |

**Hosting models**

| Model | Supported MVP? |
|-------|----------------|
| A — One org, VPS + domain | Yes, if VPS reaches cameras |
| B — On-site + VPN/tunnel | Yes (primary design) |
| C — Multi-customer one app | **No** — needs multi-tenancy |
| D — Cloud inference, LAN cameras | **No** — needs edge connector |

Hosted nodes need DNS, TLS, `CORS_ORIGINS`, firewall 80/443 only.

---

## 4. Users, roles and permissions

Hierarchy: viewer < operator < admin. **Every new API route needs an explicit `require_*` dependency.**

Target: ~20 concurrent dashboard sessions per node.

| Role | Persona | Jobs |
|------|---------|------|
| viewer | Analyst | Dashboards, analytics, reports, investigations (read) |
| operator | Operator | + incident triage, **uploads** |
| admin | Admin | + cameras/zones/rules/users, ONVIF discover |

**Route access**

| Route | Screen | Min role |
|-------|--------|----------|
| `/` | Dashboard | viewer |
| `/cameras` | Cameras | viewer read; **admin** create/update/delete |
| `/alerts` | Live alerts | viewer |
| `/incidents` | Incidents | viewer read; **operator** patch |
| `/analytics` | Analytics | viewer |
| `/reports` | Reports | viewer |
| `/investigations` | Search | viewer |
| `/assistant` | AI Assistant | viewer (+ API key) |
| `/admin` | Users, health | admin |

**API enforcement (reference):** `cameras` mutations → `require_admin`; `incidents` patch → `require_operator`; `uploads` → `require_operator`; `users` → `require_admin`.

---

## 5. Functional requirements

IDs are stable for tickets/commits. **Status** column added where useful for devs.

### 5.1 Platform and deployment

| ID | Requirement | P | Status |
|----|-------------|---|--------|
| MVP-FR-001 | Single-command deploy (full stack) | P0 | Shipped |
| MVP-FR-002 | HTTPS at nginx; HTTP→HTTPS | P0 | Shipped |
| MVP-FR-003 | Config via `.env` / pydantic-settings | P0 | Shipped |
| MVP-FR-004 | `/api/health` DB + Redis | P0 | Shipped |
| MVP-FR-005 | `/api/metrics` Prometheus | P1 | Shipped |
| MVP-FR-006 | Nightly pg_dump, 14-day retention default | P1 | Shipped (verify backup container on your host) |

### 5.2 Authentication and authorization

| ID | Requirement | P | Status |
|----|-------------|---|--------|
| MVP-FR-010 | JWT access + refresh | P0 | Shipped |
| MVP-FR-011 | Role hierarchy on API | P0 | Shipped |
| MVP-FR-012 | Bootstrap admin from env when users empty | P0 | Shipped (`BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` — **set in `.env`**, not yet in `.env.example`) |
| MVP-FR-013 | Admin user CRUD | P1 | Shipped |
| MVP-FR-014 | Audit log on admin mutations | P1 | Shipped |
| MVP-FR-015 | Fernet encryption for RTSP sources | P1 | Shipped when `FERNET_KEY` set |
| MVP-FR-016 | Redis rate limits | P1 | Shipped |

### 5.3 Camera management

| ID | Requirement | P | Status |
|----|-------------|---|--------|
| MVP-FR-020 | Sources: rtsp, snapshot_url, file | P0 | Shipped |
| MVP-FR-021 | Enable/disable; health in list | P0 | Shipped |
| MVP-FR-022 | 14 vertical profiles | P0 | Shipped |
| MVP-FR-023 | Zone editor polygons/lines | P0 | Shipped |
| MVP-FR-024 | Per-camera rules JSON | P0 | Shipped |
| MVP-FR-025 | ONVIF discover + stream URI | P1 | Shipped |
| MVP-FR-026 | Reconcile ~15s | P0 | Shipped |

**Profiles (14):** retail, supermarket, mall, bank, hotel, restaurant, hospital, school, manufacturing, warehouse, logistics, office, estate, fuel_station.

### 5.4 Video ingest and inference

| ID | Requirement | P | Status |
|----|-------------|---|--------|
| MVP-FR-030 | Bounded queues, drop-oldest | P0 | Shipped |
| MVP-FR-031 | YOLOv8 default `yolov8n.pt` | P0 | Shipped |
| MVP-FR-032 | Centroid tracking | P0 | Shipped |
| MVP-FR-033 | Zone tags + batched Postgres writes | P0 | Shipped |
| MVP-FR-034 | EasyOCR on vehicle crops (§5.9) | P0 | Shipped |
| MVP-FR-035 | Process pool `INFERENCE_WORKERS`, optional CUDA | P0 | Shipped |
| MVP-FR-036 | Memory recycle `WORKER_MEMORY_LIMIT_MB` | P1 | Shipped |
| MVP-FR-037 | File playback native FPS cap | P1 | Shipped |

### 5.5 Rule engine and incidents

| ID | Requirement | P | Status |
|----|-------------|---|--------|
| MVP-FR-040 | 8 rule types (§6) | P0 | Shipped |
| MVP-FR-041 | Rule parameters (zone, schedule, severity, …) | P0 | Shipped |
| MVP-FR-042 | Incident + annotated snapshot | P0 | Shipped |
| MVP-FR-043 | Operator patch status/assignee/notes | P0 | Shipped |
| MVP-FR-044 | Per-rule cooldown | P0 | Shipped |

### 5.6 Real-time dashboard and alerts

| ID | Requirement | P | Status |
|----|-------------|---|--------|
| MVP-FR-050 | WS `/api/ws` + JWT + camera subscribe | P0 | Shipped |
| MVP-FR-051 | Counts-only for unsubscribed cameras | P1 | Shipped |
| MVP-FR-052 | Live incidents on WS | P0 | Shipped |
| MVP-FR-053 | Dashboard KPIs via `/api/overview` | P0 | Shipped |
| MVP-FR-054 | Activity-sorted live tiles | P1 | Shipped |
| MVP-FR-055 | SMTP + HMAC webhook | P1 | Shipped |

### 5.7 Analytics and reporting

| ID | Requirement | P | Status |
|----|-------------|---|--------|
| MVP-FR-060 | Hourly buckets | P0 | **Partial** — SQL bug §0.2 |
| MVP-FR-061 | Heatmap Redis → disk | P1 | Shipped |
| MVP-FR-062 | Daily rollups + retention jobs | P1 | Shipped (hourly feed may be empty until FR-060 fixed) |
| MVP-FR-063 | Reports PDF/XLSX (5 types) | P1 | Shipped |
| MVP-FR-064 | Per-camera stats + overview | P0 | Shipped |

### 5.8 Investigations and search

| ID | Requirement | P | Status |
|----|-------------|---|--------|
| MVP-FR-070 | Detections filter + plate + cursor | P0 | Shipped |
| MVP-FR-071 | Incidents in investigations UI | P0 | Shipped |
| MVP-FR-072 | AI Assistant SELECT-only SQL | P1 | Shipped |
| MVP-FR-073 | AI Insights hourly | P1 | Shipped |
| MVP-FR-074 | Video upload jobs | P2 | **Shipped** (`/api/uploads`) |

### 5.9 Traffic surveillance and LPR

Assistive, best-effort LPR — **not** certified ANPR.

**Capabilities:** vehicle detect/track, counts, stopped_vehicle, line_crossing, OCR + search.

**User stories:** TS-01 … TS-08 (as in product brief) — all mapped below.

**Traffic requirements**

| ID | Requirement | P | Status |
|----|-------------|---|--------|
| MVP-FR-T01 | Vehicle classes YOLO | P0 | Shipped |
| MVP-FR-T02 | Persistent track_id | P0 | Shipped |
| MVP-FR-T03 | stopped_vehicle | P0 | Shipped |
| MVP-FR-T04 | line_crossing | P0 | Shipped |
| MVP-FR-T05 | Live vehicle counts | P0 | Shipped |
| MVP-FR-T06 | Hourly/daily vehicle buckets | P0 | **Partial** (rollup SQL §0.2) |
| MVP-FR-T07 | Traffic-heavy profiles | P1 | Shipped (rules only) |
| MVP-FR-T08 | Traffic camera preset wizard | P2 | **Not built** |
| MVP-FR-T09 | Vehicle queue_threshold | P2 | **Not built** |
| MVP-FR-T10 | Traffic log CSV/report | P1 | **Partial** (detections API only) |

**LPR requirements**

| ID | Requirement | P | Status |
|----|-------------|---|--------|
| MVP-FR-L01 | EasyOCR every `OCR_EVERY_N_FRAMES` | P0 | Shipped |
| MVP-FR-L02 | 4–10 alnum, `PLATE_CONFIDENCE` | P0 | Shipped |
| MVP-FR-L03 | plate_text/confidence on detections | P0 | Shipped |
| MVP-FR-L04 | 60s dedup per track | P1 | Shipped |
| MVP-FR-L05 | `[PLATE]` on live overlay | P1 | Shipped |
| MVP-FR-L06 | Investigations plate ILIKE | P0 | Shipped |
| MVP-FR-L07 | plate_logging on estate profile | P2 | **Partial** (flag unused) |
| MVP-FR-L08 | Per-camera LPR mode | P1 | **Not built** |
| MVP-FR-L09 | Watchlist | P2 | **Not built** |
| MVP-FR-L10 | Unknown vehicle at gate | P2 | **Not built** |
| MVP-FR-L11 | NL plate queries via Assistant | P1 | Shipped |
| MVP-FR-L12 | Incident snapshot + plate in description | P1 | Shipped |

**Traffic/LPR NFRs:** MVP-NFR-T01 … T05 (camera angle, thread-pool OCR, no Anthropic plates, retention).

**Traffic/LPR demo:** Required for any release touching vehicles/OCR (6 steps — supermarket sample, plate search, overlay).

**v1.1 roadmap:** L08, L09, T10, L07 enforcement, T09; edge agent v2.0.

---

## 6. Rule engine reference

Rules live in `cameras.rules` JSON. On fire: incident + snapshot + Redis.

| Rule type | Intended behavior | Typical profiles |
|-----------|-------------------|------------------|
| loitering | Dwell in zone > threshold | Bank, estate, fuel |
| stopped_vehicle | Vehicle stationary > threshold | Logistics, estate, fuel |
| zone_intrusion | Object enters restricted zone | Warehouse, office |
| after_hours_activity | Activity outside schedule | Retail, school |
| queue_threshold | People in queue zone > count | Supermarket, bank |
| crowd_density | People count > threshold | Mall, hospital |
| line_crossing | Track crosses line | Estate gate |
| abandoned_object | Static object without person | Mall, hotel |

**Adding a rule type:** evaluator in `app/rules/engine.py`, UI template in `Cameras.jsx`, cooldown, demo clip.

---

## 7. Non-functional requirements and configuration

| ID | Category | Requirement |
|----|----------|-------------|
| MVP-NFR-001 | Security | TLS; secrets in env |
| MVP-NFR-002 | Security | JWT ~30m / refresh ~7d |
| MVP-NFR-003 | Performance | `PROCESS_EVERY_N_FRAMES` default 3 |
| MVP-NFR-004 | Performance | `DASHBOARD_MAX_FPS` default 10 |
| MVP-NFR-005 | Reliability | restart policies; reconcile on startup |
| MVP-NFR-006 | Data | Retention detections 90d, snapshots 30d |
| MVP-NFR-007 | Observability | Logs, metrics, Redis health |
| MVP-NFR-008 | Capacity | 64 cameras; tune workers/memory |

**Key env vars** (see `.env.example` + set bootstrap vars in production):

| Variable | Purpose | Default (example) |
|----------|---------|-------------------|
| `MAX_CAMERAS_PER_NODE` | Cap | 64 |
| `PROCESS_EVERY_N_FRAMES` | Inference cadence | 3 |
| `OCR_EVERY_N_FRAMES` | LPR cadence | 5 |
| `PLATE_CONFIDENCE` | Min OCR confidence | 0.20 |
| `DASHBOARD_MAX_FPS` | WS frame rate cap | 10 |
| `INFERENCE_WORKERS` | YOLO pool size | 1 in `.env.example` |
| `WORKER_MEMORY_LIMIT_MB` | Worker recycle | 4096 |
| `FERNET_KEY` | RTSP encryption | unset = plaintext |
| `ANTHROPIC_API_KEY` | AI features | unset = disabled |
| `BOOTSTRAP_ADMIN_*` | First admin | required on fresh DB |

**Online:** `true` if frame in last **30s** (Redis health).

---

## 8. Data, privacy and external dependencies

Core product: **no video/DB off-node.** Hosted deployment still needs VPN/site connectivity for private RTSP.

| Data | Store | Leaves node? |
|------|-------|--------------|
| Detections, incidents, audit | Postgres | No |
| Snapshots, uploads | Media volume | No |
| Live state | Redis | No |
| Assistant | Anthropic | Text only, if key set |
| Alerts | SMTP/webhook | Metadata only, if configured |

**Assistant:** SELECT-only, allowlist, timeout, row cap — changes require security review.

---

## 9. Out of scope for MVP v1.0

Do not implement without product sign-off:

- Multi-tenancy (model C)
- Edge/cloud inference split (model D)
- End-user installs, mobile apps
- K8s / multi-node scale-out
- SSO / SAML / LDAP
- Certified ANPR, speed enforcement, watchlist (**watchlist = v1.1**)
- VMS video export (webhook JSON only)

---

## 10. Acceptance criteria and demo script

**Goals G1–G5** and **10-step demo script** unchanged from product brief: health, live video, incident, operator workflow, reports, viewer boundaries, optional Assistant, backup file.

**Release checklist:** production `.env`, TLS + `CORS_ORIGINS`, camera reachability from inference container, WebSocket after login, restore drill, pilot roles.

---

## 11. First-week checklist (backend hire)

- [ ] Clone, `cp .env.example .env`, set secrets + `BOOTSTRAP_ADMIN_*`
- [ ] `docker compose up --build`, green `/api/health`
- [ ] Add file camera (`sample_videos`), supermarket profile, queue incident live
- [ ] Trace one alert: `streams.py` → worker → `engine.py` → Redis → `ws/manager.py`
- [ ] Read all 8 rule handlers in `engine.py`
- [ ] Run `pytest tests`; fix hourly SQL in `analytics/jobs.py` (first good PR)
- [ ] Restore from `deploy/RESTORE.md`
- [ ] Skim `test_rule_engine.py`, `test_sql_validator.py`

---

## 12. Open questions and roadmap

Open questions: hosting model per customer, VPN standard, ANPR certification, plate formats v1.1, watchlist data source, pilot verticals, camera count baseline, AI upsell, SLA.

Post-MVP: multi-tenant SaaS, edge connector, SSO, K8s/GPU scale, VMS integrations, traffic/LPR v1.1 items, mobile push.

**Document control:** MVP v1.0 Developer Edition — supersedes `docs/PRD-MVP-v1.md` for engineering.

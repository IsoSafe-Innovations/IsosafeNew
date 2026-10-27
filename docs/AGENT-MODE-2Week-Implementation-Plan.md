# Iso Safe — Complete 2-Week Implementation Plan

> **Scope:** Backend / Agent Mode (Phase 1a — First Cloud Demo)
> **Branch:** `backend/agent-mode-2week-plan`
> **Status:** Planning + Repository Archaeology
> **Source PRD:** `docs/PRD-MVP-v1-Developer-Edition.md` and *Iso Safe PRD v2 Phase 1a, First Cloud Demo (2 weeks)*

---

## 0. What we are actually building

### Final objective

At the end of the two weeks, we must have this working:

```
REAL / SAMPLE CAMERA
       │
       ▼
Ubuntu Demo Box
       │
       │ existing v1 YOLO + tracking + rules
       │
       ├── HTTPS ───────► Cloud API
       │                    │
       │                    ├── PostgreSQL
       │                    ├── Redis
       │                    └── S3
       │
       └── WSS ─────────► Cloud WebSocket
                              │
                              ▼
                         Existing API/WS
                              │
                              ▼
                         React Dashboard
                              │
                              ▼
                     Browser on another network
```

The critical architectural property is:

> **The site must make outbound connections only. No inbound port forwarding is allowed.**

The PRD's one-sentence goal is essentially the existing v1 product working while the cameras and agent are on a different network from the cloud server.

---

## 1. Non-negotiable rules for the AI

Give the coding AI these rules before allowing it to modify the repository.

### PROJECT RULES

1. This is an existing production-style v1 codebase.
2. Do NOT rebuild the backend.
3. Do NOT replace existing authentication.
4. Do NOT restructure the repository.
5. Do NOT rewrite the inference pipeline.
6. Do NOT change the existing rule engine.
7. Do NOT change tracking logic.
8. Do NOT change zone logic.
9. Do NOT break existing v1 mode.

10. `AGENT_MODE` must be an additive mode.
11. When `AGENT_MODE` is unset/false: existing v1 behavior must remain unchanged.
12. When `AGENT_MODE=1`: pipeline sinks must redirect cloud-bound data to the new agent API.
13. Reuse existing models, schemas, services, Redis channels, WebSocket manager and dashboard wherever possible.
14. Do not create duplicate implementations of existing functionality.
15. Before modifying a file: inspect the current implementation and understand its dependencies.
16. After every major change: run the relevant tests.
17. Never silently remove an existing feature.
18. Never hard-code secrets.
19. Never expose S3 publicly.
20. Never introduce localhost URLs into production/staging frontend code.
21. Do not add features outside the PRD.
22. P0 requirements are mandatory.
23. P1 requirements should be implemented after all P0 requirements work.
24. P2 requirements are optional and must never delay the demo.
25. The final implementation must pass the PRD acceptance test and the existing v1 regression tests.

> This is important because the PRD specifically says the implementation should remain **one codebase, one switch**, with the existing rule engine, tracker, zones, profiles and ingestion untouched.

---

## 2. First task — AI must inspect the repository

Do not let the AI immediately start coding. Its first job is repository archaeology.

Give it this instruction:

> Before writing code, inspect the entire repository.

### Identify

**BACKEND**

- FastAPI application entrypoint
- routers
- authentication
- database models
- Alembic migrations
- incident model
- incident creation logic
- camera model
- zone model
- rule model
- Redis configuration
- Redis publishers
- WebSocket manager
- pipeline runner
- camera worker
- inference writer
- guards
- media/snapshot handling
- existing Docker files
- existing `docker-compose.yml`
- nginx configuration
- existing health endpoints
- existing test suite

**FRONTEND**

- API client
- WebSocket client
- camera pages
- camera creation/edit flow
- zones
- rules
- incident list
- incident detail
- system health
- navigation
- environment variable handling

**INFRASTRUCTURE**

- existing deployment files
- GitHub Actions
- Terraform
- Docker registry configuration
- cloud deployment configuration
- DNS/TLS configuration

### Then produce

1. Repository map
2. Relevant files
3. Existing data flow
4. Existing incident flow
5. Existing camera configuration flow
6. Existing WebSocket flow
7. Existing snapshot/media flow
8. Existing Redis channels
9. Existing authentication flow
10. Existing deployment flow
11. What can be reused unchanged
12. What must be modified
13. What new files are required
14. Potential hidden coupling risks

**DO NOT modify code during this inspection.**

This is essential because the PRD explicitly identifies the existing files where the agent mode needs to plug into the v1 pipeline.

---

## 3. Target architecture

### Existing backend — Keep

- FastAPI
- Postgres
- TimescaleDB
- Redis
- existing JWT auth
- existing v1 API
- existing WebSocket manager
- existing dashboard API
- existing inference pipeline
- existing rules
- existing tracking
- existing camera ingestion

### Add

`backend/app/api/agent.py` with:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET  | `/agent/v1/config`    | Pull camera + zone + rule configuration |
| POST | `/agent/v1/incidents`  | Push incidents (then presigned S3 PUT for snapshot) |
| POST | `/agent/v1/heartbeat`  | Agent/site health |
| WSS  | `/agent/v1/stream`     | Live frames / live events |

The PRD requires these four endpoints.

---

## 4. Two operating modes

This is the central implementation.

### Normal mode — `AGENT_MODE != 1`

```
Camera
  ↓
Existing pipeline
  ↓
Postgres / Redis / local media
```

**Nothing should change.**

### Agent mode — `AGENT_MODE=1`

```
Camera
  ↓
Existing pipeline
  ↓
Cloud sinks
```

Specifically:

| Data | Sink |
|------|------|
| configuration | `GET /agent/v1/config` |
| incidents | `POST /agent/v1/incidents` → presigned S3 PUT → snapshot |
| live frames | `WSS /agent/v1/stream` |
| health | `POST /agent/v1/heartbeat` |

---

## 5. Working agreement (this branch)

- Backend work happens only on branch `backend/agent-mode-2week-plan`.
- `main` stays clean for the other contributors.
- Phase order: **repository archaeology → P0 → P1 → P2**.
- No feature outside the PRD.
- Run tests after every major change.

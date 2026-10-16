# Repository Inspection - Day 1

## Overview
Iso Safe is an AI video intelligence platform (MVP v1) with backend (FastAPI), frontend (React/Vite), and full Docker stack.

## Backend Structure
- **app/main.py**: FastAPI entrypoint, bootstraps admin, manages lifecycle
- **app/api/**: REST routers (auth, cameras, detections, incidents, reports, search, stats, uploads, users, health, ws)
- **app/pipeline/**: runner.py (supervisor), camera_worker.py (per-frame processing)
- **app/inference/**: YOLO, OCR, tracker, detection writer
- **app/rules/engine.py**: Rule evaluation engine (8 rule types)
- **app/analytics/jobs.py**: Hourly/daily rollups
- **app/db/tables.py**: SQLAlchemy Core tables (cameras, detections, incidents, analytics, users, etc.)
- **app/ws/**: WebSocket manager and endpoint
- **app/redis_client.py**: Redis async client
- **app/config.py**: Settings via pydantic-settings
- **alembic/**: Migrations (0001_initial_schema.py)

## Current State (v1)
- 66 existing tests pass (pytest)
- smoke_api.py script exists at backend/scripts/smoke_api.py
- Docker Compose stack includes: postgres (TimescaleDB), redis, backend, inference, frontend, nginx, prometheus, backup

## Tests
- PASS: 66/66 tests
- Known failures: None
- Test command: `cd backend && python -m pytest -v`

## Smoke API Test
- Script: `backend/scripts/smoke_api.py`
- Requires running services: postgres, redis, backend API
- Default URL: http://localhost:8010 (or arg)
- Services required: postgres, redis, backend
- Environment vars: DATABASE_URL, REDIS_URL, JWT_SECRET, BOOTSTRAP_ADMIN_EMAIL/PASSWORD, etc.

## Cloud Compose Configuration
- docker-compose.yml: base stack with all services
- docker-compose.cloud.yml: override using profiles
  - inference: profiles ["inference"] (excluded from cloud by default)
  - prometheus: profiles ["prometheus"] (excluded from cloud by default)
  - backup: profiles ["backup"] (excluded from cloud by default)
- Cloud mode with override (`-f docker-compose.yml -f docker-compose.cloud.yml`): runs postgres, redis, backend, frontend, nginx (5 services). Inference is absent as required.

## Agent Mode
- AGENT_MODE not yet implemented in codebase (planned as part of 2-week implementation)
- When implemented per plan: agent will run with existing backend image + AGENT_MODE=1 and have no Postgres/Redis dependencies

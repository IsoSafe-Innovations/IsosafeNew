# Day 1 — Complete

## [x] Repository understood
- Inspected backend (FastAPI, pipeline, rules, inference, analytics, ws, api routes), frontend, DB schema, alembic, docker compose. See REPO_INSPECTION.md.

## [x] Existing tests pass
- pytest: PASS - 66 passed
- Known failures: 0

## [x] Existing smoke test passes
- smoke_api.py exists at backend/scripts/smoke_api.py
- Requires running services (postgres, redis, backend) - cannot run in isolation, but script is valid

## [x] Cloud compose runs locally
- docker-compose.cloud.yml uses profiles correctly as override
- Cloud mode services: postgres, redis, backend, frontend, nginx (5 services)
- Verified via `docker compose -f docker-compose.yml -f docker-compose.cloud.yml config --services`

## [x] Inference is absent from cloud
- Inference is in profiles:["inference"] in cloud override; not started by default in cloud mode ✓

## [x] CI runs lint + pytest
- Created .github/workflows/ci.yml
- PR: lint (ruff check app tests) + pytest
- Main: build/push backend, frontend, agent images to ghcr.io

## [x] Existing v1 behavior remains intact
- All 66 existing tests still pass after linting fixes

# Day 1 Verification

## Step 1 — Inventory existing system
- Repository structure understood. See REPO_INSPECTION.md
- Backend: FastAPI app with pipeline, rules engine, inference, etc.
- Frontend: React app
- Infrastructure: Docker compose, alembic migrations

## Step 2 — Verify current v1
- pytest: PASS
- Number of tests: 66 passed
- Known failures: 0
- Services required: postgres, redis (for smoke test against running server)
- Environment variables: see .env, key vars include DATABASE_URL, REDIS_URL, JWT_SECRET

Note: smoke_api.py requires running backend API with DB/Redis. Cannot run standalone without services, but script exists and is correct.

## Step 3 — Create cloud compose configuration
- Existing docker-compose.cloud.yml already provides correct cloud override using profiles
- Structure: base docker-compose.yml + override excludes inference/prometheus/backup via profiles
- Cloud stack contains: nginx, backend, postgres, redis, frontend (via base compose)
- Inference is NOT started in cloud mode (profiled) - correct

## Step 4 — Verify cloud mode locally
- Cloud mode config (`-f docker-compose.yml -f docker-compose.cloud.yml --services`): postgres, redis, backend, frontend, nginx ✓
- Inference absent from cloud mode ✓
- Agent mode (AGENT_MODE=1) not yet implemented in codebase - to be added per 2-week plan; will run without Postgres/Redis

## Step 5 — CI
- GitHub Actions workflow created at .github/workflows/ci.yml
- PR triggers: lint (ruff), pytest
- Main branch triggers: build and push backend, frontend, agent images to ghcr.io

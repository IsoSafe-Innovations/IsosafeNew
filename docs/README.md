# Iso Safe Documentation

Iso Safe is an on-premises AI video intelligence platform. A single node ingests
16–64 existing CCTV streams, runs YOLOv8 object detection, centroid tracking,
licence-plate OCR, and a data-driven behavioural rule engine on every feed, then
turns the results into real-time alerts, incidents, analytics, and reports in a
React dashboard.

This folder is the technical reference for the codebase. The top-level
[README](../README.md) is the short quick start; the
[PRD (Developer Edition)](PRD-MVP-v1-Developer-Edition.md) is the product
requirements and roadmap for the current single-site product, and the
[PRD v2.0 Cloud Platform](PRD-v2-Cloud-Platform.md) is the build spec for
taking it to a hosted, multi-customer cloud service. The
[Phase 1a First Cloud Demo PRD](PRD-v2-Phase-1a-First-Cloud-Demo.md) is the
2-week walking skeleton that comes first.

## Contents

| Document | What it covers |
|---|---|
| [Architecture](architecture.md) | Services, processes, data flow, Redis channels, design decisions |
| [Getting started](getting-started.md) | Production install with Docker Compose, local development setup, first login |
| [Configuration](configuration.md) | Every environment variable, its default, and what it affects |
| [Detection pipeline](pipeline.md) | Stream ingestion, batching, YOLO workers, tracking, OCR, writes, resource guards |
| [Rules, zones and profiles](rules-and-zones.md) | Rule JSON schema, all 8 rule types, zone geometry, schedules, vertical profiles |
| [Alerts and incidents](alerts-and-incidents.md) | Incident creation, snapshots, WebSocket/email/webhook fan-out, incident lifecycle |
| [Analytics, reports and AI](analytics-and-ai.md) | Hourly/daily aggregation, heatmaps, reports, natural-language search, AI insights |
| [Database](database.md) | Schema, hypertables, indexes, retention, migrations |
| [API reference](api-reference.md) | Every REST endpoint and the WebSocket protocol |
| [Frontend](frontend.md) | React app structure, auth handling, live data, and a per-screen user guide |
| [Security](security.md) | Auth model, RBAC, credential encryption, SQL guardrails, hardening checklist |
| [Operations](operations.md) | Deployment, scaling, GPU, monitoring, backups, troubleshooting |
| [Development](development.md) | Repo layout, tests, harness scripts, how to extend the system |
| [Known issues](known-issues.md) | Bugs, limitations and gaps found in the current code |

## One-paragraph mental model

Cameras are rows in PostgreSQL. The **inference** container polls that table
every 15 s and keeps one asyncio reader per enabled camera; readers push fresh
frames into tiny drop-oldest queues. An inference loop pulls one frame per camera,
batches them into a single YOLO call in a worker process, and hands detections
back to a per-camera processor that tracks objects, tags zones, reads plates,
buffers detection rows for batched insert, evaluates rules, and publishes
annotated frames and incidents to Redis. The **backend** (FastAPI) container
serves REST, relays Redis pub/sub to browser WebSockets, and never touches video
itself. Everything else — analytics, reports, AI search — is computed from the
database.

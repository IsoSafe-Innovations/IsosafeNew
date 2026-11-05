# YouTube live analysis verification — 5 November 2026

The local operational pipeline passed 12 checks against the public live source
`https://www.youtube.com/watch?v=Q71sLS8h9a4`. This is an integration check, not
an accuracy benchmark. No production deployment or AWS access was performed.

The 122-second sample produced 292 saved detection rows across car, bus, truck
and person classes, 32 track IDs, and eight deliberate test zone-intrusion
incidents. The longest track appeared in 55 detection rows. These are model
outputs, not verified unique real-world counts. The test zone covered the whole
frame and included a car rule specifically to exercise alert delivery.

Verified through the real application API and browser WebSocket protocol:

- Authenticated creation of the YouTube camera.
- Real YOLO model inference and annotated frame delivery (30 frame messages).
- Track continuity, saved zone assignments, and queryable detection records.
- Dashboard counts and camera ingestion health.
- Real rule evaluation, stored incidents, and live incident notification.
- Annotated snapshot upload and retrieval through a presigned URL using Moto S3.
- Person heatmap cells and hourly dashboard analytics from saved detections.

The first annotated message arrived after 17.34 seconds. This is a server
startup measurement, not live latency. The run does not demonstrate high-rate
analysis: 30 annotated messages were received during the sample. Fresh frames
are deliberately preferred over a growing processing backlog.

The first run exposed two failures, corrected before the passing run:

1. OCR model initialization/download blocked the shared processing loop.
   Plate reading now runs as one bounded background task per camera, with
   results associated with the originating track. Detection and alerts continue
   while OCR initializes. A regression test covers slow OCR and result association.
2. Hourly analytics SQL omitted `veh.vehicles` from its `GROUP BY`, causing a
   PostgreSQL error. The corrected query executed against the test database and
   returned dashboard analytics successfully.

The regression suite passed: 170 tests passed, one skipped.

## Limits

- No labeled ground truth was supplied. Object classification, people counts,
  false alarms, missed events, and precision/recall remain unvalidated. Distant
  objects in this view are challenging; the annotated sample includes visible
  people without corresponding boxes.
- No plate rows were recognized. OCR accuracy is not verified.
- Only zone-intrusion alerts fired in this live test. Other rule types have unit
  coverage but were not all exercised against this live scene.
- Local Moto verifies object delivery, not AWS IAM, network configuration, or
  enforcement of presigned URL expiry.
- WebSocket delivery was verified using a real client; the browser UI and
  embedded player were not exercised by this harness.

## Reproduce locally

Install backend requirements and `backend/requirements-e2e.txt`, and put the
YOLO weights at `backend/.e2e-live/yolov8n.pt`. Node must be on PATH.

From the repository root:

```powershell
docker compose -p isosafe-youtube-check -f deploy/test-youtube.compose.yml up -d --wait
Set-Location backend
& .venv/Scripts/python.exe -m scripts.verify_youtube_e2e --seconds 120
Set-Location ..
docker compose -p isosafe-youtube-check -f deploy/test-youtube.compose.yml down --volumes
```

The harness fixes all endpoints to local disposable services and resets only
the dedicated verification database. It launches the real API, pipeline, and
local storage emulator. Logs, `report.json`, `annotated-live-frame.jpg`, and
`incident-snapshot.jpg` are kept in ignored `backend/.e2e-live/`. The harness
stops the processes it starts, and the final Compose command removes its test
containers and data.

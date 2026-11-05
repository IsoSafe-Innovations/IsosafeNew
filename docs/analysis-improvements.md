# Analysis improvements and measured limits

Implemented locally on 5 November 2026. No production deployment or cloud GPU
purchase was performed. The live source used for verification is the public
YouTube video `Q71sLS8h9a4`.

## What changed

1. **Actual AI progress.** Camera ingestion health remains separate from analysis
   readiness, analysed FPS, processed frames, result/frame age, inference batch
   duration, queued/dropped frames and OCR state. Stale results show stalled or
   delayed analysis. A healthy input stream alone cannot report the AI as ready.
   Prometheus exposes `isosafe_analysis_fps` and
   `isosafe_analysis_frame_age_seconds` as well as batch inference latency.
2. **Detector choices and distant objects.** Cameras → select a camera → Analysis
   offers Fast (YOLOv8n, 640), Balanced (YOLOv8s, 960), and Detailed (YOLOv8s,
   1280). Optional overlapping tiles or up to four normalized detail regions add
   close-up passes while retaining the full frame. Predictions are remapped and
   suppressed by class. These modes cost progressively more CPU and memory.
3. **Tracking and counting.** ByteTrack and BoT-SORT are selectable alongside the
   existing centroid tracker. Counts require repeated object observations. The
   basic tracker remains the default: the small, sparsely sampled development
   set does not justify silently switching every camera. Tracking comparisons
   report coverage alongside ID switches, so missed tracks cannot look good
   merely because they produce few switches.
4. **Plate-focused OCR.** A geometric candidate localizer checks shape, minimum
   width and sharpness before OCR. An optional separately validated plate model
   can replace the geometric localizer through `PLATE_MODEL`. Readings require
   confidence ≥ 0.65 and at least three matching observations within ten seconds.
   Branding and insufficient detail abstain. One background OCR task per camera
   keeps model downloads and slow reads outside the detection/alert path.
5. **Stronger alert evidence.** Rules support evidence frames, observation-gap
   limits, directional crossings and a crossing dead band. Low-confidence or
   interrupted observations cannot accumulate the same continuous evidence.
   Conditions continue updating while alert notifications are on cooldown.
6. **Repeatable evaluation.** Administration → Accuracy checks provides local
   image labeling, optional track IDs, expected alert labels, development/test
   splits and report import. The CLI evaluates precision, recall, mAP50,
   per-frame count error, tracking coverage/ID switches, optional alert errors
   and delays, confidence sweeps, and inference speed. Unreviewed frames are
   excluded; model predictions never become reference labels automatically.

The live decoder also now paces YouTube's segmented delivery at the source
frame rate. Previously, a segment could decode in a burst, skipping so much
motion that tracking and rule confirmation became unreliable. The scheduler
uses fresh frames and rotates cameras fairly. Inference calls have a bounded
timeout and recycle only their own worker processes on failure. Worker
processes explicitly use spawn rather than forking initialized native libraries.

## Measured results

The final live run processed **241 analysis frames** in a 100-second observation
window, after startup. It delivered 114 annotated WebSocket messages, saved
912 detection rows, produced nine deliberate test alerts, and persisted five
directional car crossings. Near the end, telemetry reported **3.32 analysed
FPS**, a **219 ms batch inference time**, and a latest received-frame age of
**0.7 seconds**. The first annotated message arrived in **23.34 seconds**.

These measurements are specific to this machine, scene, settings and run.
Frame age starts when the server receives/decodes a frame; it does **not**
measure YouTube's broadcaster-to-viewer latency. Stored detection rows and track
IDs are model outputs, not verified counts of distinct real-world people.

A separate local pedestrian video exercised entry counting. Two entry events
were saved, and hourly footfall equaled those two events exactly. Entry counts
use tracker-session IDs to avoid collisions after a camera's analysis settings
restart its tracker. Test alerts used deliberately permissive test zones;
they do not demonstrate production alert accuracy.

The development detector comparison used **eight provisional assistant-reviewed
frames**, with person labels only: daytime pedestrians, a central nighttime
crosswalk ROI, a multi-pedestrian crosswalk frame, a synthetic blur derivative,
and an empty grass/building negative crop. It is neither an independent holdout
nor a comprehensive crowd/lighting benchmark. Labels need human review.

| Profile | Precision | Recall | mAP50 | Inference FPS |
|---|---:|---:|---:|---:|
| Fast | 0.947 | 0.581 | 0.584 | 9.42 |
| Balanced | 1.000 | 0.677 | 0.673 | 1.91 |
| Detailed | 0.880 | 0.710 | 0.700 | 1.08 |
| Tiled | 0.622 | 0.742 | 0.687 | 0.31 |
| Fast + focused regions | 0.667 | 0.710 | 0.692 | 4.36 |

The focused pass improved sampled recall with a smaller speed penalty than
whole-frame Detailed or Tiled modes, but produced more false positives at the
default threshold. The report includes a **development-only** threshold sweep.
No threshold or mode is automatically promoted based on these eight frames.

Raw reports: [live integration](reports/analysis-e2e-2026-11-05.json) and
[detector/tracker benchmark](reports/analysis-benchmark-2026-11-05.json).
The final regression suite passed **187 tests**, with one integration test skipped;
the frontend build and lint checks passed. A separate clear synthetic plate
(`ABC123`) was localized, read by the real OCR engine three times, and accepted
by temporal consensus. Its [smoke-test report](reports/plate-smoke-2026-11-05.json)
does not establish real plate accuracy.
Local annotated frames, snapshots, reference images, labels and comparison
predictions are retained in ignored `backend/.e2e-live/`.

## Configure a camera

Save Analysis settings in Cameras. Changes are picked up by reconciliation
within 15 seconds; a new model can take longer to download and warm up. Detail
regions can be entered as percentages or copied from a drawn polygon. Use a
region around the distant area of interest rather than enabling tiles blindly.

For visitor counts, draw a two-point line, add a Line crossing rule, select one
direction, and mark it Entry. A second rule can mark Exit. Both directions is
allowed for generic crossing counts, but cannot be called Entry or Exit. The
line orientation defines its positive/negative sides. Counts persist separately
from alert cooldowns; notification suppression does not discard crossings.

For cameras with a person Entry rule, hourly footfall uses saved entry events.
Other cameras retain unique-track estimates; these are not identity-based
visitor counts and may split/rejoin when objects are obscured. Multiple entry
lines should cover distinct entrances to avoid double-counting a person across
overlapping lines. Existing historical buckets are not automatically rewritten.

The API accepts `analysis_config` in camera create/patch requests. Options are
validated and included in agent configuration. Agent heartbeats transport
analysis telemetry. Full crossing persistence and entry-based analytics were
verified on the database-connected cloud/local worker path; standalone site
agents still follow the existing phase-1 policy of not persisting raw detections
to the cloud. Their local crossing counters must not be presented as a verified
cloud footfall history.

## Reproduce and extend the benchmark

From `backend/`, with the normal backend dependencies installed:

```powershell
& .venv/Scripts/python.exe -m scripts.capture_benchmark --source PATH_TO_VIDEO --output .e2e-live/benchmark --scenario day
```

Use Accuracy checks to import the generated dataset and its original image
files, label **every evaluated object**, and explicitly mark each reviewed frame.
Export `dataset.json` with images kept under `images/`. Optional track IDs must
be consistent across frames in one sequence. Expected alert labels can be added
after copying a camera's rules; labels and footage stay in the browser until
the user exports them. Copying rules does not modify the camera.

```powershell
& .venv/Scripts/python.exe -m scripts.benchmark_analysis .e2e-live/benchmark/dataset.json --output .e2e-live/benchmark/results --split development
```

The default comparison includes Fast, Balanced, Detailed, Tiled and Focused
modes, and centroid, ByteTrack and BoT-SORT trackers. `detail_regions` on a
reference frame specifies the camera-specific crops for the Focused comparison.
Only development runs produce confidence sweeps. Use `--split test` for final
evaluation on independent recordings; source/sequence split leakage is rejected.
`--device cuda` is available for a local GPU comparison when supported hardware
already exists. CPU measurements alone do not prove a GPU configuration or cost.

For operational verification, follow `verification-youtube-live-2026-11-05.md`
and add `--focused --tracker bytetrack --reference-video ../sample_videos/vtest.avi`
to the verification command. Optional test dependencies are in
`backend/requirements-e2e.txt`. The schema migration is `0003_camera_analysis`;
apply `alembic upgrade head` before running updated code against an existing DB.
Upgrade, downgrade to 0002 and re-upgrade were tested on a disposable database.

## Remaining validation

- Obtain and independently review representative clips from the actual camera
  views, including sustained occlusion, real motion blur, adverse lighting,
  negative events and relevant alert examples. Adjacent frames and synthetic
  variants of a clip must stay in the same data split.
- Real plate accuracy is unverified. This distant source did not yield reliable
  recognized plates. A dedicated plate detector and closer/sharper imagery may
  be needed; enlarging pixels cannot recover absent detail.
- Generic object detection does not add validated fight, fall, theft or accident
  recognition. Those capabilities need dedicated models, labels and separate
  acceptance criteria.
- Storage delivery was checked through local Moto, not live AWS permissions or
  presigned URL expiry enforcement.
- Browser interaction QA timed out waiting for desktop app access. The updated
  frontend builds and lints, and its API path was exercised by the live harness;
  interactive labeling and settings controls still need a browser review.

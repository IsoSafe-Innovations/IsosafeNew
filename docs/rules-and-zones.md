# Rules, Zones and Vertical Profiles

Rules and zones are **data**, stored as JSONB arrays on each `cameras` row and
edited through `PATCH /api/cameras/{id}` (or the camera editor in the UI). The
pipeline reloads them within 15 seconds with no restart. Adding a new rule
*instance* never needs code; adding a new rule *type* does
(see [Development › Adding a rule type](development.md#adding-a-rule-type)).

Engine: [backend/app/rules/engine.py](../backend/app/rules/engine.py).
Geometry: [backend/app/rules/zones.py](../backend/app/rules/zones.py).

## Coordinates

All geometry uses **normalized frame coordinates**: `x` and `y` run from 0 (left /
top) to 1 (right / bottom), independent of camera resolution. A track's position
is the **centre of its bounding box**.

## Zones

A camera's `zones` is a list of objects. Two shapes exist:

```json
[
  {"id": "queue", "name": "Checkout queue",
   "polygon": [[0.55, 0.40], [0.95, 0.40], [0.95, 0.95], [0.55, 0.95]]},
  {"id": "perimeter", "name": "Perimeter fence",
   "line": [[0.0, 0.62], [1.0, 0.58]]}
]
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Referenced by rules (`zone_id`) and stored in `detections.zone_ids`. The UI derives it from the name: lowercased, spaces → hyphens (`"Loading Bay"` → `loading-bay`). |
| `name` | no | Display name. |
| `polygon` | for area zones | ≥ 3 points. Membership is a ray-casting point-in-polygon test of the track centroid. |
| `line` | for perimeter lines | Exactly 2 points. Used only by `line_crossing` rules. |

Every detection row records which polygon zones its centroid was in
(`zone_ids`), so zones also drive analytics (e.g. queue metrics, which count
people in *any* zone) and investigations, even without rules.

### Drawing zones in the UI

Open **Cameras**, click a camera tile (admin), and use the zone editor over the
live frame:

- **Polygon zone:** click to add points; double-click or press *Finish* to close
  (minimum 3 points).
- **Perimeter line:** click two points.
- Type the zone **name first** — it becomes the id. Use the well-known ids below
  so profile rules bind to the zone automatically.
- Remove zones with the trash icon. Changes apply when you press **Save changes**.

## Rules

A camera's `rules` is a list of objects:

```json
{
  "id": "loiter-stockroom",
  "type": "loitering",
  "object": "person",
  "zone_id": "stockroom-entrance",
  "threshold_seconds": 30,
  "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "00:00-23:59"},
  "severity": "warning",
  "cooldown_seconds": 120
}
```

### Common fields

| Field | Default | Meaning |
|---|---|---|
| `id` | the rule `type` | Identifies the rule for cooldowns and per-track timers. **Give every rule a unique id** — two rules on one camera with the same id share a cooldown. |
| `type` | — | One of the 8 types below. Unknown types are silently ignored. |
| `zone_id` | `null` | Restricts the rule to a polygon zone. `null`, or an id that doesn't exist on the camera, means **the whole frame** (except `line_crossing`, which requires a line zone). |
| `object` | `person` | Object class the rule watches, for rules that take one. Valid classes: `person`, `car`, `motorcycle`, `bus`, `truck`, `backpack`, `suitcase`. |
| `severity` | per type (below) | `info`, `warning`, or `critical`. Must be one of these, or the incident insert fails the DB check constraint. |
| `cooldown_seconds` | `INCIDENT_COOLDOWN_SECS` (30) | After a fire, the rule is skipped entirely for this long. |
| `schedule` | always active | `{"days": [...], "hours": "HH:MM-HH:MM"}` — see below. |

### Evaluation semantics

On every processed frame, for each rule in order:

1. Skip if the schedule is not active.
2. Skip if the rule is cooling down.
3. Run the type's handler against the tracks seen in this frame.
4. If it fires, start the cooldown and emit **one** incident.

Consequences worth knowing:

- **Cooldown is per rule, not per object.** If three people loiter at once, you
  get one incident, then (after the cooldown) another if anyone is still
  loitering.
- **Each handler returns the first matching track**, which is the one boxed on
  the snapshot.
- While a rule is cooling down its handler doesn't run, so per-track state for
  that rule isn't updated during the cooldown.
- Thresholds are measured with frame timestamps, so they're in real seconds
  regardless of frame rate.

### Schedules

```json
"schedule": {"days": [0, 1, 2, 3, 4], "hours": "22:00-06:00"}
```

- `days`: weekdays when the rule is active, **Monday = 0 … Sunday = 6**. Omit for
  every day.
- `hours`: inclusive local-time window. If start > end it wraps midnight
  (`22:00-06:00` = 10 pm to 6 am). Omit for all day. A malformed value is logged
  and treated as always active.
- Time is the **pipeline container's local time** (`datetime.now()`), which is
  **UTC** in the stock Docker image. Set `TZ` on the `inference` service (and
  install `tzdata` in the image) if schedules should follow site local time.
- For overnight windows, `days` is checked against the current calendar day: a
  rule with `days: [4]` and `hours: "22:00-06:00"` is active Friday 22:00–24:00
  **and** Friday 00:00–06:00, not Saturday morning.

## Rule types

### `loitering`

A tracked object stays inside the zone longer than a threshold.

| Field | Default |
|---|---|
| `object` | `person` |
| `threshold_seconds` | `LOITER_SECONDS` (30) |
| `severity` | `warning` |

Per track, the time it was first seen inside the zone is remembered; leaving the
zone (or being a different class) resets it. Fires when `now − entered ≥
threshold`. A track that keeps loitering fires again as soon as each cooldown
ends.

### `stopped_vehicle`

A vehicle stays (almost) motionless.

| Field | Default |
|---|---|
| `threshold_seconds` | `STOPPED_VEHICLE_SECONDS` (10) |
| `severity` | `warning` |

Applies to every vehicle class (`car`, `motorcycle`, `bus`, `truck`); `object`
is ignored. An anchor position is set when the vehicle first appears in the zone
and reset whenever it moves more than `STOPPED_PIXEL_DELTA / 640` (≈ 0.023 of the
frame width/height). Fires when it has stayed within that radius for the
threshold.

### `zone_intrusion`

An object enters a restricted zone.

| Field | Default |
|---|---|
| `object` | `person` |
| `severity` | `critical` |

Fires on the **outside → inside transition** of a track. A track first detected
already inside counts as an entry. Without a `zone_id`, every new track of the
class counts as an intrusion.

### `after_hours_activity`

Any matching object is present while the rule is armed.

| Field | Default |
|---|---|
| `object` | `person` |
| `severity` | `critical` |

The `schedule` **is** the after-hours window. Fires whenever at least one
matching track is in the zone (or frame) while the schedule is active, limited by
the cooldown. Without a schedule it fires for any presence, at any time.

### `queue_threshold`

Too many people in a zone.

| Field | Default |
|---|---|
| `threshold_count` | `QUEUE_ZONE_THRESHOLD` (5) |
| `severity` | `warning` |

Counts `person` tracks in the zone this frame; fires when count ≥ threshold.
The snapshot has no highlighted box. (People only; vehicle queues are on the
roadmap.)

### `crowd_density`

Same mechanics as `queue_threshold` but intended for larger crowds.

| Field | Default |
|---|---|
| `threshold_count` | `10` |
| `severity` | `warning` |

### `line_crossing`

An object crosses a perimeter line.

| Field | Default |
|---|---|
| `zone_id` | **required** — must reference a zone with a `line` |
| `object` | `person` |
| `severity` | `critical` |

Uses the track's last two positions. Fires when they are on strictly opposite
sides of the line **and** the midpoint of the movement lies within the line's
bounding box expanded by 0.05. Crossing in either direction fires. If the zone is
missing or has no `line`, the rule never fires (there is no whole-frame
fallback).

### `abandoned_object`

A bag stays still with nobody nearby.

| Field | Default |
|---|---|
| `threshold_seconds` | `60` |
| `person_radius` | `0.15` (normalized distance) |
| `severity` | `critical` |

Watches `backpack` and `suitcase` tracks. The timer resets whenever a person's
centroid is within `person_radius` of the bag or the bag moves more than the
stopped tolerance. Fires when the bag has been stationary and unattended for the
threshold. Small or partially occluded bags are hard for `yolov8n`; consider a
larger model for this rule.

### Summary

| Type | Watches | Trigger | Key params | Default severity | Snapshot box |
|---|---|---|---|---|---|
| `loitering` | `object` | dwell in zone ≥ T | `threshold_seconds` | warning | yes |
| `stopped_vehicle` | vehicles | stationary ≥ T | `threshold_seconds` | warning | yes |
| `zone_intrusion` | `object` | enters zone | — | critical | yes |
| `after_hours_activity` | `object` | present while scheduled | `schedule` | critical | yes |
| `queue_threshold` | persons | count in zone ≥ N | `threshold_count` | warning | no |
| `crowd_density` | persons | count in zone ≥ N | `threshold_count` | warning | no |
| `line_crossing` | `object` | crosses line | line `zone_id` | critical | yes |
| `abandoned_object` | bags | unattended, still ≥ T | `threshold_seconds`, `person_radius` | critical | yes |

## Rule templates in the UI

The camera editor's **+ Add from template** menu creates a rule with a generated
id (`<type>-<base36 timestamp>`), `zone_id: null`, `cooldown_seconds: 120`, and
these presets:

| Template | Preset fields |
|---|---|
| Loitering | `object: person`, `threshold_seconds: 30`, `severity: warning` |
| Zone intrusion | `object: person`, `severity: critical` |
| Stopped vehicle | `threshold_seconds: 10`, `severity: warning` |
| After-hours activity | `object: person`, `severity: critical`, schedule every day `22:00-06:00` |
| Queue threshold | `threshold_count: 5`, `severity: info` |
| Crowd density | `threshold_count: 15`, `severity: warning` |
| Line crossing | `object: person`, `severity: critical` |
| Abandoned object | `threshold_seconds: 60`, `severity: critical` |

The editor exposes zone, severity, and threshold. Other fields (schedule,
cooldown, `object`, `person_radius`) keep their preset values; change them via
the API.

## Vertical profiles

[backend/app/profiles/registry.py](../backend/app/profiles/registry.py) defines
14 profiles. When a camera is **created** with a `vertical_profile` and an empty
`rules` list, the profile's rules are deep-copied onto the camera. The camera is
monitored immediately; rules that name a zone the camera doesn't have yet run
on the whole frame until you draw a zone with that id.

Setting or changing `vertical_profile` later via `PATCH` only updates the label;
it does **not** re-apply rules.

### Well-known zone ids

Profile rules reference these ids. Draw zones with exactly these names to bind
them:

| Zone id | Used for |
|---|---|
| `queue` | checkout / counter queues (`queue_threshold`, some `crowd_density`) |
| `restricted` | stockrooms, vaults, plant floors (`zone_intrusion`) |
| `entrance` | lobby entrances (`loitering`) |
| `gate` | site gates, docks (`loitering`, `stopped_vehicle`) |
| `perimeter` | fence lines — **must be a line zone** (`line_crossing`) |

### Profile catalogue

Schedules are shown as `days hours`; "daily" = all seven days. Cooldowns in
seconds.

| Profile | Rules (type · zone · threshold · severity · cooldown · schedule) |
|---|---|
| `retail` — Retail Store | loitering · frame · 120 s · warning · 300 · — ; after_hours · frame · — · critical · 120 · daily 22:00-06:00 ; queue_threshold · `queue` · 5 · info · 600 |
| `supermarket` — Supermarket | queue_threshold · `queue` · 6 · warning · 600 ; crowd_density · frame · 25 · warning · 900 ; zone_intrusion · `restricted` · — · warning · 300 ; after_hours · frame · — · critical · 120 · daily 23:00-05:00 |
| `mall` — Shopping Mall | crowd_density · frame · 40 · warning · 900 ; abandoned_object · frame · 90 s · critical · 300 ; after_hours · frame · — · critical · 120 · daily 22:30-06:00 |
| `bank` — Bank Branch | loitering · `entrance` · 60 s · warning · 300 ; abandoned_object · frame · 45 s · critical · 300 ; zone_intrusion · `restricted` · — · critical · 60 ; after_hours · frame · — · critical · 60 · daily 19:00-07:00 ; queue_threshold · `queue` · 8 · info · 600 |
| `hotel` — Hotel | loitering · `entrance` · 300 s · info · 600 ; abandoned_object · frame · 120 s · warning · 600 ; zone_intrusion · `restricted` · — · warning · 300 |
| `restaurant` — Restaurant | queue_threshold · `queue` · 5 · info · 600 ; after_hours · frame · — · critical · 120 · daily 01:00-06:00 |
| `hospital` — Hospital | zone_intrusion · `restricted` · — · critical · 120 ; crowd_density · `queue` · 15 · warning · 600 ; abandoned_object · frame · 90 s · warning · 600 |
| `school` — School | line_crossing · `perimeter` · — · critical · 60 · Sat–Sun all day ; after_hours · frame · — · critical · 120 · daily 20:00-06:00 ; loitering · `gate` · 300 s · warning · 600 |
| `manufacturing` — Manufacturing Plant | zone_intrusion · `restricted` · — · critical · 60 ; after_hours · frame · — · critical · 120 · daily 22:00-06:00 ; stopped_vehicle · `gate` · 300 s · info · 600 |
| `warehouse` — Warehouse | after_hours · frame · — · critical · 120 · daily 21:00-06:00 ; stopped_vehicle · `gate` · 900 s · info · 1800 ; zone_intrusion · `restricted` · — · warning · 300 |
| `logistics` — Logistics Depot | stopped_vehicle · `gate` · 600 s · warning · 900 ; line_crossing · `perimeter` · — · critical · 60 ; after_hours · frame · — · critical · 120 · daily 22:00-05:00 |
| `office` — Office Building | after_hours · frame · — · warning · 300 · daily 21:00-06:00 ; zone_intrusion · `restricted` · — · warning · 300 |
| `estate` — Residential Estate | line_crossing · `perimeter` · — · critical · 60 ; zone_intrusion · `restricted` · — · critical · 120 ; loitering · `gate` · 120 s · warning · 300 ; stopped_vehicle · `gate` · 120 s · info · 600 |
| `fuel_station` — Fuel Station | stopped_vehicle · frame · 600 s · warning · 600 ; loitering · frame · 300 s · warning · 600 ; after_hours · frame · — · critical · 120 · daily 00:00-05:00 |

Profiles also carry `kpi_cards`, `default_reports`, and (estate) a
`plate_logging` flag. These are returned by `GET /api/cameras/profiles` but are
**not used** anywhere yet: the dashboard KPIs are fixed and OCR runs on all
vehicles regardless of profile.

### A note on profile rules without zones

Until you draw the referenced zone:

- `zone_intrusion` on `restricted` fires for **every new person** in frame —
  noisy on a busy camera. Draw the `restricted` zone promptly, or remove the
  rule.
- `queue_threshold` on `queue` counts everyone in frame.
- `line_crossing` on `perimeter` never fires.

## Tuning tips

- Start thresholds high and lower them; false positives erode operator trust
  faster than misses.
- Use longer `cooldown_seconds` for informational rules (queues, crowds) and
  shorter ones for critical security rules.
- Because detection runs every `PROCESS_EVERY_N_FRAMES` frames, very fast line
  crossings can be missed if the object moves past the line's bounding box
  between two processed frames. Lower `PROCESS_EVERY_N_FRAMES` for perimeter
  cameras if capacity allows.
- If tracks fragment (new ids for the same person), dwell-based rules
  (`loitering`, `abandoned_object`) restart their timers. Fragmentation usually
  comes from low frame rates or occlusion; the 0.12 match gate assumes objects
  move less than ~12 % of the frame between processed frames.

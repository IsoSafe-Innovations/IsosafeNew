# Analytics, Reports and AI

## Analytics aggregation

Raw detections are far too numerous to chart directly, so the pipeline rolls
them up. Code: [backend/app/analytics/jobs.py](../backend/app/analytics/jobs.py).
All jobs run inside the **inference** container.

| Job | Schedule | Effect |
|---|---|---|
| `aggregate_current_hour` | every 5 min | Upsert one `analytics_hourly` row per camera for the **current UTC hour** from `detections` + `incidents` |
| `snapshot_heatmaps` | first loop run after startup, then once per new UTC hour | Persist each camera's Redis heatmap grid to JSON files, then clear it |
| `run_daily_rollup` | 02:00 UTC | Upsert `analytics_daily` for **yesterday** (UTC) from `analytics_hourly` |
| `prune_snapshots` | 02:00 UTC | Delete snapshot JPEGs older than `RETENTION_SNAPSHOTS_DAYS` |
| `cleanup_stuck_uploads` | 02:00 UTC | Mark `upload_jobs` still `processing` after 6 h as `error` / `timed out` |

### Hourly metrics

For each camera and hour bucket (`date_trunc('hour', ts)`, UTC):

| Column | Definition |
|---|---|
| `footfall` | Number of distinct `person` track ids seen in the hour |
| `vehicles` | JSON object `{class: distinct track ids}` for `car`, `motorcycle`, `bus`, `truck` |
| `avg_queue` / `max_queue` | Per second, count `person` detection rows that were inside *any* polygon zone; average and max of those per-second counts (seconds with nobody in a zone aren't included) |
| `avg_occupancy` | Per minute, count distinct `person` tracks; average over minutes in which at least one person was detected |
| `incident_count` | Incidents created on the camera in the hour |

Interpretation caveats:

- **Footfall counts tracks, not people.** A person who leaves and re-enters, or
  whose track fragments due to occlusion, counts more than once. Track ids
  restart at 1 when the pipeline restarts, so ids reused within one hour can
  undercount.
- **Queue metrics use any zone.** A camera with several zones mixes them. Draw
  queue cameras with a single queue zone for meaningful queue stats.
- Only the current hour is recomputed. Data that arrives between the last
  5-minute run of an hour and the top of the next hour is never re-aggregated
  into that hour's bucket.

> The PRD lists a `GroupingError` from this upsert as a known bug — hourly
> buckets may not update. The query also runs four correlated LATERAL subqueries
> per detection row, which becomes expensive at high detection volumes. See
> [Known issues](known-issues.md#hourly-analytics-upsert).

### Daily rollup

`analytics_daily` sums footfall and incident counts, averages the averages,
takes the max of `max_queue`, merges the vehicles JSON by key, and records
`peak_hour` — the UTC hour with the highest footfall. It currently feeds no API
endpoint or screen, but it is queryable by the AI assistant.

### Heatmaps

The pipeline increments a 32×32 grid in Redis for every processed `person`
track position. The hourly job writes two files per camera:

```
MEDIA_ROOT/heatmaps/<camera_id>_<YYYY-MM-DDTHH>.json   archive
MEDIA_ROOT/heatmaps/<camera_id>_latest.json            what the UI shows
```

```json
{"camera_id": "cam-3f9a12c0", "hour": "2026-10-07T11", "grid": [[0, 0, 3, ...], ...]}
```

`grid[y][x]` is the hit count for cell `(x, y)`; the `hour` is when the snapshot
was taken, so the data covers the preceding hour. Cell values are per processed
frame, so a person standing still adds a hit every frame — heatmaps measure
**dwell**, not unique visitors. Heatmap files are never pruned.

### Dashboard KPIs (`GET /api/overview`)

Computed from `analytics_hourly` for **today** (UTC midnight → now) and
**yesterday**:

- `footfall`, `vehicles` (sum over all classes), `avg_occupancy`, `incidents`
- `open_incidents` — current `open` + `investigating` count
- `suspicious_today` — `warning` + `critical` incidents since UTC midnight

The dashboard shows the today-vs-yesterday percentage change. Because yesterday
is a full day and today is partial, deltas are naturally negative early in the
day.

## Reports

`GET /api/reports/{report_type}?format=pdf|xlsx&from=&to=` (viewer+), code in
[backend/app/api/reports.py](../backend/app/api/reports.py). If `from`/`to` are
omitted, `to = now` and `from` defaults per type:

| Report | Default period | PDF table | XLSX |
|---|---|---|---|
| `daily_summary` | 1 day | per-camera footfall + incident count, sorted by footfall | Summary sheet + Incidents sheet |
| `weekly_security` | 7 days | incident log (time, camera, type, severity, status), first 200 | same |
| `monthly_business` | 30 days | per-camera footfall + incident count | same |
| `incident_report` | 7 days | incident log, first 200 | same |
| `camera_health` | 1 day | camera inventory: id, type, profile, enabled | same |

Every PDF has a title, the UTC period, and a summary line (total footfall,
incidents with critical count, camera count). Every XLSX has:

- **Summary** — one row per `analytics_hourly` bucket in the period: camera,
  bucket, footfall, avg/max queue, avg occupancy, incidents.
- **Incidents** — every incident in the period with description.

The `camera_health` report lists configuration only; it doesn't include live
health (FPS, reconnects, uptime) — use **Administration → System Health** for
that. Reports are generated synchronously in the request; very long periods on
busy nodes take a while.

The UI's Reports page downloads with the default periods (it has no date
picker). Use the API to choose a custom range:

```bash
curl -k -H "Authorization: Bearer $TOKEN" -o march.pdf "https://isosafe.lan/api/reports/monthly_business?format=pdf&from=2026-03-01T00:00:00Z&to=2026-04-01T00:00:00Z"
```

## AI features (optional)

Both features require `ANTHROPIC_API_KEY` on the **backend** container and use
`ANTHROPIC_MODEL` (default `claude-sonnet-4-6`). Without a key:

- `POST /api/search` returns **503** "AI search is not configured on this node".
- `GET /api/insights` returns `{"available": false, ...}`; the UI shows a
  disabled message.
- Nothing else is affected.

### Natural-language search (AI Assistant)

[backend/app/search/nl_search.py](../backend/app/search/nl_search.py)

```mermaid
sequenceDiagram
    participant U as Operator
    participant API as POST /api/search
    participant C as Anthropic API
    participant V as validate_select_only
    participant PG as PostgreSQL

    U->>API: "Which camera had the most loitering alerts this week?"
    API->>C: system = schema DDL + rules, user = question
    C-->>API: {"sql": "...", "explanation": "..."}
    API->>V: SQL
    V-->>API: cleaned SQL or SQLValidationError (422)
    API->>PG: BEGIN READ ONLY; SET LOCAL statement_timeout = 5000; SELECT ...
    PG-->>API: rows
    API-->>U: sql, explanation, columns, rows (≤100), row_count
```

The model receives a condensed DDL of five tables (`cameras` without `source`,
`detections`, `incidents`, `analytics_hourly`, `analytics_daily`) and is told to
return a single SELECT with a LIMIT ≤ 100, no semicolons or comments, as a JSON
object. The UI always displays the generated SQL and explanation next to the
results so operators can judge them.

#### SQL guardrails

Every generated statement passes
[`validate_select_only`](../backend/app/search/validator.py) before execution:

| Check | Rejects |
|---|---|
| Comments | `--`, `/*`, `*/`, `#` anywhere |
| Semicolons | any `;` (blocks stacked queries) |
| First keyword | anything other than `SELECT` or `WITH` |
| Forbidden keywords (word-boundary, case-insensitive) | `insert update delete drop alter create truncate grant revoke copy call do execute prepare vacuum analyze reindex cluster listen notify lock comment security set reset show merge refresh discard declare fetch move checkpoint load import pg_read_file pg_write_file pg_sleep dblink lo_import lo_export` |
| System catalogs | any `pg_` identifier, `information_schema` |
| Table allowlist | `FROM`/`JOIN` targets other than the five tables above or CTE names defined in the statement (so `users`, `audit_log`, `upload_jobs` are unreachable) |

Then, as defence in depth, the query runs in a `READ ONLY` transaction with a
5-second `statement_timeout`, and results are truncated to 100 rows.

Side effects of the keyword blocklist: legitimate questions whose SQL contains a
blocked word — even inside a string literal, e.g. `description ILIKE '%lock%'` or
a column alias `AS set` — are rejected with 422 "Generated SQL rejected:
Forbidden keyword". Rephrasing usually helps.

Rate limit: 20 requests / minute per client IP.

Errors: 422 for an empty query, invalid model output, or validator rejection;
503 when unconfigured; 500 for execution errors (e.g. timeout, SQL error).

### AI insights

[backend/app/search/insights.py](../backend/app/search/insights.py)

Each run sends Claude:

- every `analytics_hourly` row from the last 24 hours, and
- up to 50 `open` / `investigating` incidents (camera id, time, type, severity,
  description, status),

and asks for 3–6 observations as a JSON array:

```json
[
  {"title": "Staff the tills 17:00-19:00", "detail": "Queue length peaked at 9 on cam-... ...", "kind": "staffing"},
  {"title": "Repeated after-hours activity at the dock", "detail": "...", "kind": "risk"}
]
```

`kind` is one of `staffing`, `risk`, `pattern`, `anomaly`. The result is cached
in Redis (`isosafe:insights`, TTL 24 h) with a `generated_at` timestamp and served
by `GET /api/insights`. A response that isn't a JSON array is discarded (logged,
previous cache kept).

Scheduling: each API worker runs an insights loop that first fires **one hour
after startup** and then hourly. So a fresh install shows "No insights generated
yet" until the first hour passes or someone presses refresh
(`POST /api/insights/refresh`, rate-limited to 4/hour per IP). With
`API_WORKERS=2`, two workers each call the API every hour.

### Data sent to Anthropic

| Feature | Sent | Never sent |
|---|---|---|
| Search | the operator's question text, the schema DDL and instructions | frames, video, snapshots, query results, camera sources |
| Insights | last-24h hourly aggregates (camera ids, counts, averages) and open-incident summaries including their generated descriptions | frames, video, snapshots, raw detections, plates, camera sources, user data |

Search results are executed and returned locally; they are not sent back to the
model. If insights' aggregate data must also stay on-premises, leave
`ANTHROPIC_API_KEY` unset.

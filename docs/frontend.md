# Frontend

A React 18 single-page app built with Vite 5, styled with Tailwind CSS 3, charts
by Recharts, icons by lucide-react, routing by React Router 6. Source:
[frontend/src](../frontend/src). There is no state-management library and no
TypeScript; data is fetched per view with small hooks.

## Build and serve

| Mode | Command | Notes |
|---|---|---|
| Dev | `npm run dev` | `http://localhost:5173`; proxies `/api` (with WebSocket upgrade) and `/media` to `http://localhost:8000` ([vite.config.js](../frontend/vite.config.js)) |
| Build | `npm run build` | outputs `dist/` |
| Docker | `frontend/Dockerfile` | Node 22 build stage → `nginx:1.27-alpine` serving `dist/` with SPA fallback ([nginx-spa.conf](../frontend/nginx-spa.conf)); `/assets/` cached 1 year (immutable, content-hashed) |

In production the outer `nginx` service proxies `/` to this container and
`/api`, `/media` elsewhere, so the SPA always calls same-origin relative paths.

## Structure

```
src/
  main.jsx             BrowserRouter → AuthProvider → App
  App.jsx              shows <Login/> until signed in, then <Layout> + routes
  index.css            Tailwind layers + alert-pulse animation
  lib/
    api.js             fetch wrapper: JWT header, auto-refresh on 401, errors
    format.js          severity colours, time/number formatting, labels
  hooks/
    useAuth.jsx        auth context: user, login, logout, hasRole(min)
    usePolling.jsx     GET a path every N ms → {data, error, loading, refresh}
    useWebSocket.jsx   one shared socket; listeners; camera subscriptions
  components/
    Layout.jsx         top nav, notifications bell, user menu
    CameraTile.jsx     live/thumbnail camera card
    ZoneEditor.jsx     draw polygons/lines over the live frame
    KpiCard.jsx        dashboard metric card
  views/               one component per route
```

### Routes

| Path | View | Visible to |
|---|---|---|
| `/` | Dashboard | all |
| `/cameras` | Cameras | all (editing: admin) |
| `/alerts` | AI Alerts | all |
| `/incidents`, `/incidents/:id` | Incidents (list + detail modal) | all (managing: operator+) |
| `/analytics` | Analytics | all |
| `/reports` | Reports | all |
| `/investigations` | Investigations | all |
| `/assistant` | AI Assistant | all |
| `/admin` | Administration | admin (nav item hidden for others) |
| `*` | redirect to `/` | |

Role gating in the UI is cosmetic; the API enforces every permission.

## Authentication flow

[lib/api.js](../frontend/src/lib/api.js) and
[hooks/useAuth.jsx](../frontend/src/hooks/useAuth.jsx):

1. `login(email, password)` posts to `/api/auth/login`, stores
   `isosafe_access`, `isosafe_refresh` and `isosafe_user` (`{email, role}`) in
   `localStorage`.
2. Every `api()` call adds `Authorization: Bearer <access>` (except auth
   routes) and sets `Content-Type: application/json` for non-FormData bodies.
3. On **401**, it calls `/api/auth/refresh` once and retries the request. If the
   refresh fails, tokens are cleared, the logout handler resets the user, and
   the app returns to the login screen.
4. Token changes dispatch a `isosafe:tokens-changed` window event, which makes
   the WebSocket reconnect with the new access token.
5. Non-OK responses throw an `Error` whose message is the API's `detail` and
   whose `status` is the HTTP code; JSON responses are parsed, others (report
   downloads) are returned as the raw `Response`.

Because the role is cached in `localStorage`, a role change shows in the UI only
after the user signs out and in again.

## Live data

### Polling

`usePolling(path, intervalMs, enabled)` fetches immediately and then on an
interval, re-starting when `path` changes. Intervals used:

| Data | Interval |
|---|---|
| `/api/counts` (dashboard) | 5 s |
| `/api/cameras` | 15 s (Dashboard, Cameras, Admin) / 60 s elsewhere |
| `/api/incidents` | 20 s (Incidents), 30 s (Alerts) |
| `/api/overview` | 30 s |
| `/api/stats/...` | 60 s |
| `/api/insights` | 5 min |
| `/api/heatmap/...` | 5 min |

### WebSocket

[hooks/useWebSocket.jsx](../frontend/src/hooks/useWebSocket.jsx) keeps **one
module-level socket** for the whole app.

- Components call `useWebSocket(onMessage)` to register a listener and get
  `subscribe(ids)` / `unsubscribe(ids)`. The module keeps the union of all
  subscribed camera ids and sends it as a `set` action whenever it changes and
  on every (re)connect.
- On close it refreshes the access token, then reconnects after 3 s.
- `useLiveAlerts(max)` collects `incident` messages since page load (newest
  first, capped). It does not load history.

`CameraTile` with `live` subscribes to its camera's frames; without `live` it
only uses the `counts` messages every client receives.

## Screen guide

### Login

Email + password. Errors from the API are shown inline.

### Dashboard

- **KPI row:** People Today, Vehicles (with % vs yesterday), Active Cameras
  (online / total), Incidents (open + investigating), Suspicious Activities
  (warning + critical today), Avg Occupancy. Each card links to the relevant
  screen.
- **Camera grid, prioritized by activity:** enabled cameras sorted by the number
  of objects currently in frame (then online first). The top 6 get live video;
  the first is large; click a tile to expand it. The rest show counts only.
  Each tile shows a LIVE badge, a **RISK** level (HIGH after a critical alert,
  MED after a warning, for 15 s), people/vehicle counts in frame, and the
  camera's unique people count since the pipeline started.
- **Hourly Footfall (24h)** bar chart across all cameras.
- **Live Alerts** received this session, and the cached **AI Insights**.

### Cameras

A live tile per camera with FPS, reconnects, and rule count. Admins also get:

- **Add camera** — name, source type, source URL/path, optional vertical
  profile (shows its rule count).
- **ONVIF Discovery** — scans the network and lists devices; **Use** pre-fills
  the add form. The pre-filled value is the device's ONVIF service address, not
  an RTSP stream; replace it with the stream URL (from the camera's manual or
  `POST /api/cameras/discover/stream-uri`).
- Click a tile to **edit**: draw zones on the live frame, add rules from
  templates, set each rule's zone, severity and threshold, toggle **Stream
  enabled**, **Save changes**, or **Delete**. See
  [Rules, zones and profiles](rules-and-zones.md).

### AI Alerts

A feed combining alerts received live this session (marked ● LIVE) with the
50 most recent incidents from the API. Click an alert to open the incident.

### Incidents

Filterable table (status, severity, camera; latest 200). Clicking a row opens a
detail modal with the snapshot. Operators and admins can change status, assign
(admins see a user list; operators can only unassign), and write notes (saved
when the field loses focus).

### Analytics

Per camera or all cameras, over 24 h / 7 days / 30 days: footfall (area),
vehicles (bars), queue length avg/max, occupancy & incidents. For a single
camera, a 32×32 **movement heatmap** from the last hourly snapshot.

### Reports

Five report cards, each with PDF and Excel buttons, using each report's default
period. See [Analytics › Reports](analytics-and-ai.md#reports).

### Investigations

Forensic search across detections and incidents: from/to (browser local time,
converted to UTC), camera, object type, plate substring. Shows matching
incidents as snapshot cards and detections in a table with **Load more**
(cursor pagination, 50 per page).

### AI Assistant

Chat-style natural-language questions with example prompts. Each answer shows
the explanation, the generated SQL, and a results table. The right column shows
AI insights with a regenerate button. If no API key is configured, the page
explains how to enable it. History lives only in the browser tab.

### Administration (admin)

- **Users & Roles** — create users (min 8-char password), change roles inline,
  delete. (There's no UI to reset another user's password; use
  `PATCH /api/users/{id}` with `{"password": ...}` or `scripts/reset_admin.py`.)
- **Footage Upload** — upload a video for single-pass analysis; shows the
  generated camera id. (The API allows operators to upload, but this panel is
  only on the admin page.)
- **System Health** — API / Database / Redis status, cameras online, and a
  per-camera table of status, FPS, reconnects, dropped frames.

## Styling

Dark theme only. Tailwind extensions in
[tailwind.config.js](../frontend/tailwind.config.js):

| Token | Value | Use |
|---|---|---|
| `surface-950…600` | `#0a0e17` → `#2b3548` | backgrounds and borders |
| `normal` | `#22c55e` | healthy / online |
| `info` | `#3b82f6` | primary actions, info severity |
| `warning` | `#f59e0b` | warning severity |
| `critical` | `#ef4444` | critical severity, errors |

`alert-pulse` (in `index.css`) animates tiles with an active alert.

## Adding a screen

1. Create `src/views/MyView.jsx`; fetch with `usePolling` or `get()` from
   `lib/api`.
2. Add a `<Route>` in `App.jsx` and a `NAV` entry in `components/Layout.jsx`
   (use `minRole` to hide it from lower roles).
3. Guard actions with `hasRole('operator' | 'admin')` from `useAuth()`, and make
   sure the backend endpoint enforces the same role.

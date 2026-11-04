# Security

Iso Safe is designed for on-premises networks: video, frames and the database
never leave the site. This document describes the controls that exist in the
code, their limits, and what to configure before going to production.

## Threat model in brief

| Asset | Main risks | Controls |
|---|---|---|
| Live video and snapshots | unauthorized viewing | JWT on API/WebSocket, TLS; **snapshots under `/media` are public** (see below) |
| Camera credentials | disclosure via API, DB dump, logs | Fernet encryption at rest, redaction in responses, masked in audit log |
| Incident and detection data | tampering, unauthorized changes | RBAC, audit log of mutations |
| Database | SQL injection via AI search | SELECT-only validator, table allowlist, read-only transaction, timeout |
| Accounts | credential stuffing | bcrypt, login rate limit |

## Authentication

[backend/app/security.py](../backend/app/security.py),
[backend/app/api/auth.py](../backend/app/api/auth.py)

- Passwords are hashed with **bcrypt** (random salt per hash). Minimum length 8
  for users created through the API; there are no complexity rules.
- Tokens are **HS256 JWTs** signed with `JWT_SECRET`, with a `type` claim so a
  refresh token can't be used as an access token and vice versa.
  - Access token: `ACCESS_TOKEN_MINUTES` (30).
  - Refresh token: `REFRESH_TOKEN_DAYS` (7). Refresh re-reads the user, so
    deleted users can't refresh and role changes are picked up.
- There is **no server-side revocation**: logout only discards tokens in the
  browser, and old refresh tokens remain valid until expiry. To force everyone
  out, rotate `JWT_SECRET` and restart the backend.
- The bootstrap admin is created only when the `users` table is empty. If
  `BOOTSTRAP_ADMIN_PASSWORD` is blank, a random password is printed in the
  backend log — rotate it after first login.
- The frontend stores tokens in `localStorage`, which any script running on the
  origin can read. Keep the origin free of third-party scripts.

## Authorization (RBAC)

Three ranked roles, enforced per endpoint by `require_role()` in
[backend/app/api/deps.py](../backend/app/api/deps.py):

| Capability | viewer | operator | admin |
|---|:-:|:-:|:-:|
| View dashboards, cameras, live video, incidents, analytics, reports, investigations | ✓ | ✓ | ✓ |
| AI search and insights refresh | ✓ | ✓ | ✓ |
| Update incidents (status, assignment, notes) | | ✓ | ✓ |
| Upload footage | | ✓ | ✓ |
| Create / edit / delete cameras, zones, rules | | | ✓ |
| ONVIF discovery | | | ✓ |
| Manage users | | | ✓ |

The role is carried in the access token, so a demotion takes effect when the
user's current access token expires (≤ 30 min) or is refreshed.

## Camera credential protection

- `cameras.source` is encrypted with **Fernet** (AES-128-CBC + HMAC-SHA256) when
  `FERNET_KEY` is set, stored as `enc:<token>`. Without a key, sources are stored
  in plaintext — set the key before adding cameras.
- API responses redact credentials: `rtsp://user:pass@host/...` →
  `rtsp://***@host/...`.
- Audit entries mask `source` as `***`.
- The decrypted source exists only in the inference process memory.

Not covered: upload camera sources (file paths) contain no secrets; snapshot URL
sources with credentials in the query string (`?user=…&pwd=…`) are encrypted at
rest but **not** redacted in API responses, because redaction only handles the
`user:pass@` form.

### Rotating the Fernet key

There is no built-in re-encryption. To rotate:

1. While the old key is still configured, read each camera's plaintext source
   (e.g. a one-off script calling `app.security.decrypt_source` on every row).
2. Set the new `FERNET_KEY` in `.env`, restart `backend` and `inference`.
3. `PATCH /api/cameras/{id}` each camera with its plaintext source; the API
   re-encrypts with the new key.

If the old key is lost, re-enter every camera's source.

## AI search guardrails

Generated SQL is validated before execution (comments, semicolons, non-SELECT
statements, ~40 forbidden keywords, system catalogs, and non-allowlisted tables
are rejected), then executed in a `READ ONLY` transaction with a 5-second
statement timeout and a 100-row cap. `users`, `audit_log`, `upload_jobs`, and
the camera `source` column are outside the allowlist / schema description. See
[Analytics › SQL guardrails](analytics-and-ai.md#sql-guardrails).

The validator is regex-based, not a SQL parser, and the query runs as the same
database role the application uses. For defence in depth, create a dedicated
read-only role with `SELECT` on only the five allowlisted tables and use it for
the search pool (requires a small code change to give the search its own DSN).

## Audit log

Every mutating admin/operator action writes to `audit_log`: camera
create/update/delete, user create/update/delete, incident updates, uploads. Audit
writes are best-effort (failures are logged, not raised). Logins, failed logins,
and reads are not audited. There's no API or UI for the audit log; query the
table directly ([Database](database.md#audit_log)).

## Transport security

- nginx terminates TLS 1.2/1.3 on 443 and redirects port 80 to HTTPS.
- It adds `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY`.
- Not set by default: HSTS, Content-Security-Policy, Referrer-Policy. Add them
  in [deploy/nginx.conf](../deploy/nginx.conf) once you have a trusted
  certificate.
- Internal traffic (backend ↔ postgres/redis/inference) is unencrypted on the
  Docker bridge network. Redis has no password; neither Redis nor Postgres
  publishes ports to the host in the default Compose file — keep it that way.

## Media files

`/media/` is served by nginx straight from the media volume with **no
authentication**. Anyone who can reach the node over HTTPS and knows or guesses a
path can download incident snapshots, heatmap files, and uploaded footage.
Snapshot filenames contain the camera id and a millisecond timestamp, which
makes them hard but not impossible to guess; upload filenames are random UUIDs.

Mitigations, from simplest:

- Restrict the node to a trusted VLAN / VPN.
- Protect `/media/` in nginx with `auth_request` to a small backend endpoint that
  validates the bearer token (the frontend would then need to fetch images with
  the header, or use short-lived signed URLs).

## WebSocket

The access token is passed in the query string (`/api/ws?token=…`) because
browsers can't set headers on WebSocket handshakes. Query strings can end up in
proxy access logs; the bundled nginx config uses the default access log format,
which includes the request line. Disable or redact access logging for
`/api/ws`, or keep log access restricted. The token is checked once at connect;
an open socket outlives the token's expiry until it disconnects.

## Rate limiting

Login (10/min), refresh (30/min), search (20/min) and insights refresh (4/h) are
rate limited per `request.client.host`. Behind the bundled nginx every request
appears to come from the nginx container, so the limits apply to the whole node
rather than per user — one person mistyping passwords can lock everyone out of
login for a minute. Fix by trusting the proxy's forwarded address (run Uvicorn
with `--proxy-headers --forwarded-allow-ips=<nginx>` and have nginx set
`X-Forwarded-For`), or key on `X-Real-IP`, which nginx already sends. See
[Known issues](known-issues.md#rate-limits-are-global-behind-nginx).

## Uploads

Only `.mp4 .avi .mov .mkv .webm` extensions are accepted, size-capped at
`UPLOAD_MAX_MB`, streamed to disk in 1 MB chunks, and named by a random UUID
(user-supplied names are never used as paths). Contents are not validated; files
are decoded by OpenCV/FFmpeg in the inference container, so keep its base image
patched.

## Secrets

All secrets live in `.env` (git-ignored). Required: `JWT_SECRET`, `FERNET_KEY`,
`POSTGRES_PASSWORD`. Optional: `SMTP_PASSWORD`, `WEBHOOK_SECRET`,
`ANTHROPIC_API_KEY`. The code default `JWT_SECRET` is
`dev-secret-do-not-use-in-prod` — the app does **not** refuse to start with it,
so check it's overridden.

## Production hardening checklist

- [ ] Long random `JWT_SECRET`, `POSTGRES_PASSWORD`, `WEBHOOK_SECRET`.
- [ ] `FERNET_KEY` set **before** adding cameras, backed up somewhere safe.
- [ ] Bootstrap admin password changed after first login; create named admin
      accounts and avoid sharing one.
- [ ] CA-issued TLS certificate; add HSTS and a CSP in nginx.
- [ ] `CORS_ORIGINS` set to the real dashboard origin only.
- [ ] Node reachable only from the security operations network/VPN (also protects
      `/media`).
- [ ] Access logging for `/api/ws` disabled or restricted.
- [ ] Rate limiting fixed to use the real client IP.
- [ ] Postgres and Redis ports not published; consider a Redis password.
- [ ] Decide whether AI insights' aggregate data may leave the site; otherwise
      leave `ANTHROPIC_API_KEY` empty.
- [ ] Backups copied off the node, and the restore procedure tested.

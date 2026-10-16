# On-site Agent

One-command Docker install for the site box (Ubuntu mini PC). The agent is the
**same image as the cloud API**, run with `AGENT_MODE=1`: it pulls its camera
config from the cloud, opens the local RTSP/file streams, runs YOLO inference,
and ships incidents, snapshots and heartbeats back over the authenticated agent
channel. It keeps **no database and no inbound ports**.

```
Camera ─► Agent (this box) ──outbound 443──► Cloud API ─► Postgres + S3 ─► Dashboard
```

## Requirements

- Docker on Ubuntu 22.04+ (any Docker host works).
- **Outbound HTTPS 443 to the cloud only.** No port forwarding, no VPN, no
  inbound firewall rules. The agent dials out and keeps the connection open.
- CPU is plenty for the demo; a GPU is optional.

## 1. Get the cloud URL and agent token

From the cloud bootstrap secrets: `CLOUD_URL` (e.g. `https://demo.example.com`)
and `AGENT_TOKEN`.

## 2. One-command install

```bash
docker run -d --name isosafe-agent --restart unless-stopped \
  -e AGENT_MODE=1 \
  -e CLOUD_URL=https://demo.example.com \
  -e AGENT_TOKEN=<agent-token> \
  -v isosafe-models:/data/models \
  -v /opt/isosafe/sample_videos:/data/sample_videos:ro \
  ghcr.io/isosafe-innovations/isosafenew/agent:latest
```

- The image default command is the pipeline runner; no extra args are needed.
- `isosafe-models` persists the YOLO weights across upgrades (fetched on first run).
- The `sample_videos` mount is only needed for the file-based acceptance test (step 4).

Verify the handshake:

```bash
docker logs -f isosafe-agent     # expect: "agent config version=... cameras=N"
curl -s -H "Authorization: Bearer $AGENT_TOKEN" \
  https://demo.example.com/agent/v1/config | jq '.config_version, (.cameras|length)'
curl -s https://demo.example.com/api/health | jq .agent   # {"online": true, ...}
```

## 3. Add the camera

Cloud dashboard → **Cameras** → **Add camera**.

- **RTSP (real camera):** source `rtsp://192.168.1.10:554/stream1`, type `rtsp`.
- **File (acceptance test):** source `/data/sample_videos/vtest.avi`, type `file`.

The agent reconciles every 15 s, so a new camera starts within one cycle.

## 4. Acceptance: RTSP + `vtest.avi`

```bash
# on the agent box
sudo mkdir -p /opt/isosafe/sample_videos
sudo cp sample_videos/vtest.avi /opt/isosafe/sample_videos/   # from the repo
```

- **vtest.avi:** add the `file` camera above and confirm it goes online with
  `fps > 0`, then detections/incidents appear in the dashboard.
- **RTSP:** point a `rtsp` camera at the real device and confirm the same, plus
  System Health shows per-camera FPS, reconnects and dropped frames.

## 5. Latency (p95 ≤ 2 s)

The end-to-end detection → dashboard latency is measured with the load harness
(it opens WebSocket clients and reports alert-latency percentiles):

```bash
cd backend
python -m scripts.load_test --base https://demo.example.com \
  --email <admin@…> --password <pw> \
  --video /data/sample_videos/vtest.avi --minutes 30
# -> "alert latency p95=…" (PASS if < 1 s, well under the 2 s budget)
```

In-cluster Prometheus also exposes `isosafe_alert_dispatch_latency_seconds`:

```
histogram_quantile(0.95, rate(isosafe_alert_dispatch_latency_seconds_bucket[5m]))
```

## 6. Network test (no inbound ports)

Run the agent from a **phone hotspot** (or any network that drops all inbound
traffic) and confirm heartbeats, frames and incidents still reach the cloud. Only
outbound 443 to `CLOUD_URL` is required.

## 7. Upgrade

Images are tagged `:latest` and `:<git-sha>`. Config lives in the cloud, so a
restart is safe:

```bash
docker pull ghcr.io/isosafe-innovations/isosafenew/agent:latest
docker rm -f isosafe-agent
# re-run the step-2 command
```

`watchtower` can automate the pull/restart.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `agent config fetch failed` | Check `CLOUD_URL` reachability and `AGENT_TOKEN`. |
| Camera never goes online | `ffprobe <source>` from the box; check the RTSP credentials. |
| First start slow | It downloads YOLO weights (~6 MB) into the models volume. |
| 403 on cloud calls | Token rotated in the cloud; update `AGENT_TOKEN` and restart. |

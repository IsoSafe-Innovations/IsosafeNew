"""24 h stability soak monitor (PRD v2 Phase 1a DEMO-NFR-04).

Samples the running stack once per interval and appends one JSON object per
tick to a JSONL log. At the end it prints a summary and fails (non-zero exit)
if the run did not meet the target: no container restarts and ≤ 20 % growth in
container memory versus the first sample.

Usage (run from the repo root, stack already ``docker compose up``):

    python -m scripts.soak --base-url https://demo.example.com --hours 24

The default network call goes to the local stack (http://localhost:8000); pass
``--base-url`` for the deployed demo. Metrics come from the existing Prometheus
endpoint ``/api/metrics``; container CPU/RAM/restarts come from the Docker CLI.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time

import httpx

# Prometheus metric names we care about (see app/metrics.py).
_METRIC_RE = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{[^}]*\})?\s+(?P<value>[0-9.eE+-]+)$")
_MEM_RE = re.compile(r"([0-9.]+)\s*([KMG]i?B)")


def parse_mem(text: str) -> int | None:
    """Parse Docker's '123.4MiB / 1.5GiB' usage into bytes."""
    m = _MEM_RE.match(text.strip())
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2)
    factor = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3,
              "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3}[unit]
    return int(value * factor)


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout


def compose_containers(compose_files: list[str], project: str | None) -> dict[str, str]:
    """Return {service: container_id} for the running compose project."""
    cmd = ["docker", "compose"]
    for f in compose_files:
        cmd += ["-f", f]
    if project:
        cmd += ["-p", project]
    cmd += ["ps", "--format", "json"]
    out = _run(cmd)
    mapping: dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        service = row.get("Service") or row.get("Name")
        cid = row.get("ID") or row.get("Name")
        if service and cid:
            mapping[service] = cid
    return mapping


def container_stats(container_ids: dict[str, str]) -> dict[str, dict]:
    """CPU%, memory bytes and restart count per service."""
    if not container_ids:
        return {}
    ids = list(container_ids.values())
    names = {v: k for k, v in container_ids.items()}
    out = _run(["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids])
    stats: dict[str, dict] = {}
    for line in out.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        cid = row.get("ID") or row.get("Container") or row.get("Name")
        service = names.get(cid, row.get("Name"))
        cpu = float(row.get("CPUPerc", "0").rstrip("%") or 0)
        mem = parse_mem(row.get("MemUsage", "").split("/")[0])
        stats[service] = {"cpu_pct": cpu, "mem_bytes": mem}
    for service, cid in container_ids.items():
        restarts = _run(["docker", "inspect", "-f", "{{.RestartCount}}", cid]).strip()
        stats.setdefault(service, {})["restarts"] = int(restarts or 0)
    return stats


def parse_metrics(text: str) -> dict:
    """Extract the soak-relevant gauges/counters from the Prometheus text."""
    incidents = 0.0
    reconnects = 0.0
    ws = None
    fps: list[float] = []
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        m = _METRIC_RE.match(line.strip())
        if not m:
            continue
        name, value = m.group("name"), float(m.group("value"))
        if name == "isosafe_incidents_total":
            incidents += value
        elif name == "isosafe_stream_reconnects_total":
            reconnects += value
        elif name == "isosafe_ws_clients":
            ws = value
        elif name == "isosafe_camera_fps":
            fps.append(value)
    return {
        "incidents_total": incidents,
        "stream_reconnects_total": reconnects,
        "ws_clients": ws,
        "camera_fps": fps,
    }


def sample(base_url: str, containers: dict[str, str]) -> dict:
    tick: dict = {"ts": dt.datetime.now(dt.UTC).isoformat()}
    tick["containers"] = container_stats(containers)
    try:
        health = httpx.get(base_url.rstrip("/") + "/api/health", timeout=10).json()
        tick["health"] = {
            "status": health.get("status"),
            "database_ok": health.get("database", {}).get("ok"),
            "redis_ok": health.get("redis", {}).get("ok"),
            "agent_online": (health.get("agent") or {}).get("online"),
            "agent_last_seen_ago": (health.get("agent") or {}).get("last_seen_ago"),
        }
    except Exception as e:  # noqa: BLE001 - soak should never die on a blip
        tick["health"] = {"error": type(e).__name__}
    try:
        raw = httpx.get(base_url.rstrip("/") + "/api/metrics", timeout=10).text
        tick["metrics"] = parse_metrics(raw)
    except Exception as e:  # noqa: BLE001
        tick["metrics"] = {"error": type(e).__name__}
    return tick


def total_mem(tick: dict) -> int:
    return sum(
        c.get("mem_bytes") or 0 for c in tick.get("containers", {}).values()
    )


def total_restarts(tick: dict) -> int:
    return sum(c.get("restarts") or 0 for c in tick.get("containers", {}).values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--compose", action="append", default=None,
                    help="compose file (repeatable); default base + cloud")
    ap.add_argument("--project", default=None, help="compose project name (-p)")
    ap.add_argument("--out", default=None, help="JSONL log path")
    ap.add_argument("--max-mem-growth-pct", type=float, default=20.0)
    args = ap.parse_args()

    compose_files = args.compose or ["docker-compose.yml", "docker-compose.cloud.yml"]
    out = args.out or f"soak-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    deadline = time.monotonic() + args.hours * 3600
    baseline_mem: int | None = None
    samples: list[dict] = []
    print(f"soak: logging to {out} for {args.hours}h (interval {args.interval}s)")

    with open(out, "w", encoding="utf-8") as fh:
        while time.monotonic() < deadline:
            containers = compose_containers(compose_files, args.project)
            tick = sample(args.base_url, containers)
            fh.write(json.dumps(tick) + "\n")
            fh.flush()
            samples.append(tick)
            if baseline_mem is None:
                baseline_mem = total_mem(tick)
            mem = total_mem(tick)
            growth = ((mem - baseline_mem) / baseline_mem * 100) if baseline_mem else 0.0
            print(
                f"[{tick['ts']}] mem={mem/1024/1024:.0f}MiB "
                f"growth={growth:+.1f}% restarts={total_restarts(tick)} "
                f"agent={tick['health'].get('agent_online')} "
                f"({tick['metrics'].get('incidents_total', 0):.0f} incidents)"
            )
            time.sleep(args.interval)

    growths = []
    if baseline_mem:
        growths = [
            (total_mem(t) - baseline_mem) / baseline_mem * 100 for t in samples
        ]
    max_growth = max(growths) if growths else 0.0
    restarts = total_restarts(samples[-1]) if samples else 0
    degraded = sum(1 for t in samples if t["health"].get("status") not in (None, "ok"))
    agent_offline_ticks = sum(1 for t in samples if t["health"].get("agent_online") is False)

    print("\n--- soak summary ---")
    print(f"samples: {len(samples)}  duration: {args.hours}h")
    print(f"max memory growth: {max_growth:+.1f}% (limit {args.max_mem_growth_pct}%)")
    print(f"container restarts: {restarts}")
    print(f"degraded health ticks: {degraded}")
    print(f"agent-offline ticks: {agent_offline_ticks}")

    ok = restarts == 0 and max_growth <= args.max_mem_growth_pct
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

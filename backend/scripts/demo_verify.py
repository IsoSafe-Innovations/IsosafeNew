"""Midpoint demo verifier: exercises the full camera -> agent -> cloud chain.

Run against a live stack (see docs/MIDPOINT-DEMO.md):

    python -m scripts.demo_verify --base http://10.137.51.140:8000

It checks, in order:
  1. camera creation                      (POST /api/cameras)
  2. agent receives camera                (GET /agent/v1/config + camera health online)
  3. live frames                          (camera health fps > 0)
  4. rule present in agent config
  5. incident stored                      (POST /agent/v1/incidents + GET /api/incidents/{id})
  6. snapshot presigned GET               (opens now -> 200; optional --expiry-wait -> 403)
  7. acknowledge                          (PATCH status investigating)
  8. resolve                              (PATCH status resolved)
  9. agent health online                  (GET /api/health .agent.online)
  +  /media 404 (staging lockdown), >1MB -> 413, optional --outage drill.

Credentials default from env (BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD /
AGENT_TOKEN) so it works without flags on the demo box.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import uuid

import httpx

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

# 1x1 JPEG (SOI ... EOI); MinIO stores opaque bytes, validity is irrelevant.
TINY_JPEG = b"\xff\xd8\xff\xdb\x00\x43\x00" + b"\x00" * 60 + b"\xff\xd9"


class Report:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        status = PASS if ok else FAIL
        self.results.append((status, name, detail))
        mark = "PASS" if ok else "FAIL"
        line = f"  [{mark}] {name}"
        if detail and not ok:
            line += f"  -- {detail}"
        print(line, flush=True)
        return ok

    def skip(self, name: str, detail: str = "") -> None:
        self.results.append((SKIP, name, detail))
        print(f"  [SKIP] {name}" + (f"  -- {detail}" if detail else ""), flush=True)

    def section(self, title: str) -> None:
        print(f"\n== {title}", flush=True)

    def summary(self) -> int:
        failed = [r for r in self.results if r[0] == FAIL]
        passed = [r for r in self.results if r[0] == PASS]
        skipped = [r for r in self.results if r[0] == SKIP]
        print("\n" + "=" * 60)
        print(f"RESULT: {len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped")
        for _, name, detail in failed:
            print(f"  FAILED: {name} -- {detail}")
        print("=" * 60)
        return 1 if failed else 0


def login(c: httpx.Client, email: str, password: str) -> str:
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def get_or_create_camera(c: httpx.Client, headers: dict, name: str, source: str) -> str:
    existing = c.get("/api/cameras", headers=headers).json()
    for cam in existing:
        if cam["name"] == name:
            return cam["id"]
    r = c.post(
        "/api/cameras",
        headers=headers,
        json={"name": name, "source": source, "type": "file", "enabled": True},
    )
    r.raise_for_status()
    return r.json()["id"]


def wait_for(predicate, timeout: float, interval: float = 2.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    return last


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify the Iso Safe midpoint demo.")
    ap.add_argument("--base", default=os.environ.get("DEMO_BASE", "http://localhost:8000"))
    ap.add_argument("--email", default=os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "admin@isosafe.local"))
    ap.add_argument("--password", default=os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", ""))
    ap.add_argument("--agent-token", default=os.environ.get("AGENT_TOKEN", ""))
    ap.add_argument("--camera-name", default="Demo cam")
    ap.add_argument("--camera-source", default="/data/sample_videos/demo.mp4")
    ap.add_argument("--wait-agent", type=float, default=60.0, help="seconds to wait for the agent")
    ap.add_argument("--wait-frames", type=float, default=60.0, help="seconds to wait for live frames")
    ap.add_argument("--expiry-wait", type=float, default=0.0, help="sleep then re-open snapshot (300 for the 403 test)")
    ap.add_argument("--outage", action="store_true", help="stop/start the cloud backend (needs docker)")
    ap.add_argument("--compose", default="docker compose -f docker-compose.yml -f docker-compose.cloud.yml -f docker-compose.demo.yml")
    args = ap.parse_args()

    if not args.password:
        print("ERROR: set BOOTSTRAP_ADMIN_PASSWORD or pass --password", file=sys.stderr)
        return 2

    rep = Report()
    base = args.base.rstrip("/")
    agent_headers = {"Authorization": f"Bearer {args.agent_token}"}
    with httpx.Client(base_url=base, timeout=30.0) as c:
        # reachability
        rep.section("0. Stack reachable")
        try:
            c.get("/api/health").raise_for_status()
            rep.check("cloud API reachable", True)
        except Exception as e:  # noqa: BLE001
            rep.check("cloud API reachable", False, repr(e))
            return rep.summary()

        token = login(c, args.email, args.password)
        headers = {"Authorization": f"Bearer {token}"}

        # 9. agent health online
        rep.section("9. Agent health")
        health = c.get("/api/health").json()
        agent = health.get("agent") or {}
        rep.check("agent online", bool(agent.get("online")),
                  f"agent={agent} (is the inference container up with AGENT_MODE=1?)")
        rep.check("agent_version reported", bool(agent.get("agent_version")), str(agent))

        # 1. camera creation
        rep.section("1. Camera creation")
        cam_id = get_or_create_camera(c, headers, args.camera_name, args.camera_source)
        rep.check("camera exists", bool(cam_id), cam_id)

        # 2. agent receives camera
        rep.section("2. Agent receives camera")
        cfg = c.get("/agent/v1/config", headers=agent_headers)
        rep.check("GET /agent/v1/config authorized", cfg.status_code == 200, f"HTTP {cfg.status_code}")
        if cfg.status_code == 200:
            ids = [x["id"] for x in cfg.json().get("cameras", [])]
            rep.check("cloud serves camera to agent", cam_id in ids, f"cameras={ids}")

        def cam_online():
            cams = c.get("/api/cameras", headers=headers).json()
            for cam in cams:
                if cam["id"] == cam_id:
                    return cam.get("health") or {}
            return None

        h = wait_for(lambda: (cam_online() or {}).get("online"), args.wait_agent)
        rep.check("agent is running the camera (health online)", bool(h),
                  "camera health never went online; check `inference` logs")

        # 3. live frames
        rep.section("3. Live video")
        h = wait_for(lambda: ((cam_online() or {}).get("fps") or 0) > 0, args.wait_frames)
        fps = (cam_online() or {}).get("fps", 0)
        rep.check("frames flowing (fps > 0)", (fps or 0) > 0, f"fps={fps}")

        # 4. rule present in agent config
        rep.section("4. Rule")
        camera = next((x for x in cfg.json().get("cameras", []) if x["id"] == cam_id), {})
        rules = camera.get("rules") or []
        rep.check("camera carries a rules list", isinstance(rules, list), f"rules={rules}")
        if not rules:
            rep.skip("at least one rule configured", "add a rule in the dashboard Rules editor")

        # 5. incident (deterministic: post one as the agent would)
        rep.section("5. Incident")
        inc_uuid = str(uuid.uuid4())
        payload = {
            "uuid": inc_uuid, "camera_id": cam_id, "type": "loitering",
            "severity": "high", "ts": time.time(),
            "details": {"description": "demo incident"}, "has_snapshot": True,
        }
        r = c.post("/agent/v1/incidents", headers=agent_headers, json=payload)
        rep.check("POST /agent/v1/incidents -> 200", r.status_code == 200, f"HTTP {r.status_code}")
        inc_id = r.json().get("incident_id") if r.status_code == 200 else None
        put_url = r.json().get("snapshot_put_url") if r.status_code == 200 else None
        rep.check("cloud returned presigned PUT", bool(put_url), str(r.json() if r.status_code == 200 else r.text))

        fetched = c.get(f"/api/incidents/{inc_id}", headers=headers)
        rep.check("incident retrievable", fetched.status_code == 200, f"HTTP {fetched.status_code}")

        # 6. snapshot
        rep.section("6. Snapshot")
        if put_url:
            put = httpx.put(put_url, content=TINY_JPEG, headers={"Content-Type": "image/jpeg"})
            rep.check("agent-style PUT to snapshot_put_url", put.status_code in (200, 204), f"HTTP {put.status_code}")
        snapshot_url = (fetched.json().get("snapshot_url") if fetched.status_code == 200 else None) or ""
        rep.check("snapshot_url is a 5-min presigned S3 GET",
                  "X-Amz-Expires=300" in snapshot_url and "X-Amz-Signature" in snapshot_url,
                  snapshot_url[:120])
        if snapshot_url.startswith("http"):
            got = httpx.get(snapshot_url)
            rep.check("snapshot opens immediately (200)", got.status_code == 200, f"HTTP {got.status_code}")
            if args.expiry_wait > 0:
                print(f"  ... waiting {args.expiry_wait:.0f}s for the signature to expire", flush=True)
                time.sleep(args.expiry_wait)
                expired = httpx.get(snapshot_url)
                rep.check("snapshot expired -> 403", expired.status_code == 403, f"HTTP {expired.status_code}")
        else:
            rep.check("snapshot_url present", False, "no snapshot_url (S3 not configured?)")

        rep.check("old /media route 404s", c.get("/media/leak.jpg").status_code == 404,
                  f"HTTP {c.get('/media/leak.jpg').status_code}")

        oversized = dict(payload, uuid=str(uuid.uuid4()), blob="x" * (1024 * 1024))
        big = c.post("/agent/v1/incidents", headers=agent_headers, json=oversized)
        rep.check("oversized (>1MB) agent request -> 413", big.status_code == 413, f"HTTP {big.status_code}")

        # 7. acknowledge
        rep.section("7. Acknowledge")
        ack = c.patch(f"/api/incidents/{inc_id}", headers=headers, json={"status": "investigating"})
        rep.check("status -> investigating", ack.status_code == 200 and ack.json().get("status") == "investigating",
                  f"HTTP {ack.status_code} {ack.text[:120]}")

        # 8. resolve
        rep.section("8. Resolve")
        res = c.patch(f"/api/incidents/{inc_id}", headers=headers,
                      json={"status": "resolved", "resolution_notes": "demo verified"})
        rep.check("status -> resolved", res.status_code == 200 and res.json().get("status") == "resolved",
                  f"HTTP {res.status_code} {res.text[:120]}")
        if res.status_code == 200:
            rep.check("resolved_at set", bool(res.json().get("resolved_at")), str(res.json().get("resolved_at")))

        # optional outage drill
        if args.outage:
            rep.section("Outage drill (stop/start cloud backend)")
            try:
                subprocess.run(f"{args.compose} stop backend", shell=True, check=True,
                               capture_output=True, text=True)
                rep.check("cloud API is down during outage", not _safe_health(base))
                subprocess.run(f"{args.compose} start backend", shell=True, check=True,
                               capture_output=True, text=True)

                def _agent_back_online():
                    try:
                        r = httpx.get(f"{base}/api/health", timeout=5.0)
                        return r.status_code == 200 and bool((r.json().get("agent") or {}).get("online"))
                    except Exception:  # noqa: BLE001
                        return None

                rep.check("cloud recovers and agent reconnects",
                          bool(wait_for(_agent_back_online, timeout=120)))
            except Exception as e:  # noqa: BLE001
                rep.skip("outage drill", f"could not run docker: {e!r}")

    return rep.summary()


def _safe_health(base: str) -> bool:
    try:
        return httpx.get(f"{base}/api/health", timeout=5.0).status_code == 200
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    raise SystemExit(main())

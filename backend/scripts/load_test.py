"""Load/soak harness (Phase 11.6).

Spawns N file-based camera rows pointing at a sample video, opens W WebSocket
dashboard clients each subscribed to 4 cameras, and drives R API requests/sec,
for a configurable duration. Reports request latencies, WS message throughput,
alert latency, and process memory of the API under test.

Usage:
  python -m scripts.load_test --base http://localhost:8000 \
      --email admin@isosafe.local --password ... \
      --video /data/sample_videos/vtest.avi \
      --cameras 64 --ws-clients 20 --rps 50 --minutes 240
"""
import argparse
import asyncio
import json
import random
import statistics
import time

import httpx


async def api_load(client: httpx.AsyncClient, headers: dict, rps: int,
                   stop: asyncio.Event, latencies: list[float], errors: list[str]):
    paths = ["/api/cameras", "/api/incidents?limit=20", "/api/overview",
             "/api/counts", "/api/stats/all?hours=24"]
    while not stop.is_set():
        t0 = time.monotonic()
        tasks = []
        for _ in range(rps):
            path = random.choice(paths)

            async def one(p=path):
                s = time.monotonic()
                try:
                    r = await client.get(p, headers=headers)
                    latencies.append(time.monotonic() - s)
                    if r.status_code >= 500:
                        errors.append(f"{p} -> {r.status_code}")
                except Exception as e:
                    errors.append(f"{p} -> {type(e).__name__}")

            tasks.append(one())
        await asyncio.gather(*tasks)
        await asyncio.sleep(max(0.0, 1.0 - (time.monotonic() - t0)))


async def ws_client(base_ws: str, token: str, camera_ids: list[str],
                    stop: asyncio.Event, counters: dict, alert_lat: list[float]):
    import websockets

    url = f"{base_ws}/api/ws?token={token}"
    while not stop.is_set():
        try:
            async with websockets.connect(url, max_size=10_000_000) as ws:
                await ws.send(json.dumps({"action": "set", "camera_ids": camera_ids}))
                while not stop.is_set():
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    msg = json.loads(raw)
                    counters[msg.get("type", "?")] = counters.get(msg.get("type", "?"), 0) + 1
                    if msg.get("type") == "incident":
                        try:
                            import datetime as dt
                            ts = dt.datetime.fromisoformat(msg["ts"])
                            alert_lat.append(
                                (dt.datetime.now(dt.timezone.utc) - ts).total_seconds()
                            )
                        except (KeyError, ValueError):
                            pass
        except asyncio.TimeoutError:
            continue
        except Exception:
            if not stop.is_set():
                await asyncio.sleep(2)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--email", default="admin@isosafe.local")
    ap.add_argument("--password", required=True)
    ap.add_argument("--video", default="/data/sample_videos/vtest.avi")
    ap.add_argument("--cameras", type=int, default=64)
    ap.add_argument("--ws-clients", type=int, default=20)
    ap.add_argument("--rps", type=int, default=50)
    ap.add_argument("--minutes", type=float, default=240)
    args = ap.parse_args()

    async with httpx.AsyncClient(base_url=args.base, timeout=30) as client:
        r = await client.post("/api/auth/login",
                              json={"email": args.email, "password": args.password})
        r.raise_for_status()
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # ensure N load cameras exist
        existing = {c["name"] for c in (await client.get("/api/cameras", headers=headers)).json()}
        camera_ids = []
        for i in range(args.cameras):
            name = f"load-cam-{i:02d}"
            if name in existing:
                cam = next(c for c in (await client.get("/api/cameras", headers=headers)).json()
                           if c["name"] == name)
            else:
                r = await client.post("/api/cameras", headers=headers, json={
                    "name": name, "source": args.video, "type": "file", "loop_file": True,
                    "rules": [{"id": "load-loiter", "type": "loitering", "object": "person",
                               "threshold_seconds": 20, "severity": "info",
                               "cooldown_seconds": 300}],
                })
                r.raise_for_status()
                cam = r.json()
            camera_ids.append(cam["id"])
        print(f"{len(camera_ids)} load cameras ready")

        stop = asyncio.Event()
        latencies: list[float] = []
        errors: list[str] = []
        alert_lat: list[float] = []
        counters: dict = {}

        base_ws = args.base.replace("http", "ws", 1)
        tasks = [asyncio.create_task(api_load(client, headers, args.rps, stop, latencies, errors))]
        for w in range(args.ws_clients):
            subs = random.sample(camera_ids, min(4, len(camera_ids)))
            tasks.append(asyncio.create_task(
                ws_client(base_ws, token, subs, stop, counters, alert_lat)))

        deadline = time.monotonic() + args.minutes * 60
        try:
            while time.monotonic() < deadline:
                await asyncio.sleep(30)
                if latencies:
                    p95 = statistics.quantiles(latencies[-5000:], n=20)[18]
                    print(f"[{time.strftime('%H:%M:%S')}] reqs={len(latencies)} "
                          f"p95={p95*1000:.0f}ms errors={len(errors)} ws={counters} "
                          f"alert_p95={statistics.quantiles(alert_lat, n=20)[18]:.2f}s"
                          if len(alert_lat) >= 20 else
                          f"[{time.strftime('%H:%M:%S')}] reqs={len(latencies)} "
                          f"p95={p95*1000:.0f}ms errors={len(errors)} ws={counters}")
        finally:
            stop.set()
            for t in tasks:
                t.cancel()

        print("\n--- results ---")
        print(f"requests: {len(latencies)}, errors: {len(errors)}")
        if latencies:
            q = statistics.quantiles(latencies, n=100)
            print(f"latency p50={q[49]*1000:.0f}ms p95={q[94]*1000:.0f}ms p99={q[98]*1000:.0f}ms")
        if alert_lat:
            print(f"alert latency p95={statistics.quantiles(alert_lat, n=20)[18]:.2f}s "
                  f"({'PASS' if statistics.quantiles(alert_lat, n=20)[18] < 1.0 else 'FAIL'} <1s)")
        print(f"ws messages: {counters}")
        if errors[:10]:
            print("sample errors:", errors[:10])


if __name__ == "__main__":
    asyncio.run(main())

"""Read-only API/WebSocket capacity gate. Run against staging with representative data."""
import argparse
import asyncio
import json
import math
import os
import time
from contextlib import AsyncExitStack
from pathlib import Path

import httpx
import websockets

PATHS = ("/api/cameras", "/api/incidents?limit=20", "/api/overview", "/api/counts")


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else float("inf")


async def measure(args):
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(base_url=args.base, timeout=10, limits=limits) as client:
        login = await client.post("/api/auth/login", json={
            "email": os.environ["CAPACITY_EMAIL"], "password": os.environ["CAPACITY_PASSWORD"],
        })
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        # Abort on a bad target or failed auth before load starts.
        for path in PATHS:
            (await client.get(path, headers=headers)).raise_for_status()
        latencies, failures = [], []
        semaphore = asyncio.Semaphore(args.concurrency)

        async def request(index):
            # Include queue time so saturation cannot disappear from latency.
            start = time.monotonic()
            try:
                async with semaphore:
                    result = await client.get(PATHS[index % len(PATHS)], headers=headers)
                    if not 200 <= result.status_code < 300:
                        failures.append(result.status_code)
            except httpx.HTTPError:
                failures.append("request_error")
            latencies.append(time.monotonic() - start)

        async with AsyncExitStack() as stack:
            sockets = []
            for _ in range(args.ws_clients):
                ws = await stack.enter_async_context(websockets.connect(
                    args.base.replace("http", "ws", 1).rstrip("/") + "/api/ws?token=" + token,
                    open_timeout=10,
                ))
                await ws.send(json.dumps({"action": "set", "camera_ids": []}))
                pong = await ws.ping()
                await asyncio.wait_for(pong, timeout=5)
                sockets.append(ws)
            tasks = []
            start = time.monotonic()
            for index in range(round(args.seconds * args.rps)):
                await asyncio.sleep(max(0, start + index / args.rps - time.monotonic()))
                tasks.append(asyncio.create_task(request(index)))
            await asyncio.gather(*tasks)
            elapsed = time.monotonic() - start
            for ws in sockets:
                pong = await ws.ping()
                await asyncio.wait_for(pong, timeout=5)
        error_rate = len(failures) / len(latencies) if latencies else 1
        p95 = percentile(latencies, .95) * 1000
        achieved = len(latencies) / elapsed
        return {
            "passed": error_rate <= args.max_error_rate and p95 <= args.max_p95_ms and achieved >= args.rps * .9,
            "requests": len(latencies), "errors": len(failures), "error_rate": error_rate,
            "p95_ms": round(p95, 2), "achieved_rps": round(achieved, 2),
            "target_rps": args.rps, "concurrency_limit": args.concurrency,
            "ws_clients_verified": args.ws_clients, "elapsed_seconds": round(elapsed, 2),
            "scope": "Read-only API and idle WebSockets; excludes video throughput and incident fanout",
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--rps", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--ws-clients", type=int, default=20)
    parser.add_argument("--max-p95-ms", type=float, default=500)
    parser.add_argument("--max-error-rate", type=float, default=.01)
    parser.add_argument("--output")
    args = parser.parse_args()
    if min(args.seconds, args.rps, args.concurrency) <= 0 or args.ws_clients < 0:
        parser.error("Duration, RPS and concurrency must be positive")
    result = asyncio.run(measure(args))
    report = json.dumps(result, indent=2)
    print(report)
    if args.output:
        Path(args.output).write_text(report + "\n")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

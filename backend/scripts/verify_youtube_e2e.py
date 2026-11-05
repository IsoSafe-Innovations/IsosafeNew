"""Real-model local YouTube verification, using disposable services only.

Start deploy/test-youtube.compose.yml first. Requires moto[server], the backend
dependencies, Node on PATH and .e2e-live/yolov8n.pt. Artifacts stay in .e2e-live.
This checks operational delivery, not accuracy against labeled ground truth.
"""
import argparse
import asyncio
import base64
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
import sqlalchemy as sa
import websockets


async def verify(args, root, artifacts, processes, files):
    environment = os.environ.copy()
    environment.update({
        "DATABASE_URL": "postgresql+asyncpg://verification:verification-only@127.0.0.1:15439/verification",
        "REDIS_URL": "redis://127.0.0.1:16389/0",
        "MEDIA_ROOT": str(artifacts / "media"),
        "JWT_SECRET": "verification-only-secret-at-least-32-characters",
        "AGENT_TOKEN": "verification-only-agent", "AGENT_MODE": "1",
        "CLOUD_URL": "http://127.0.0.1:18765", "PIPELINE_UPLOADS_ONLY": "0",
        "BOOTSTRAP_ADMIN_EMAIL": "verification@example.com",
        "BOOTSTRAP_ADMIN_PASSWORD": "verification-only-password",
        "S3_ENDPOINT_URL": "http://127.0.0.1:19090",
        "S3_PUBLIC_ENDPOINT_URL": "http://127.0.0.1:19090",
        "S3_ACCESS_KEY": "verification", "S3_SECRET_KEY": "verification-only",
        "S3_BUCKET": "verification-snapshots", "S3_REGION": "us-east-1",
        "ANTHROPIC_API_KEY": "", "SMTP_HOST": "", "WEBHOOK_URL": "",
        "CAMERA_SECRET_KEY": "", "FERNET_KEY": "", "AWS_EC2_METADATA_DISABLED": "true",
        "INFERENCE_WORKERS": "1", "INFERENCE_BATCH_SIZE": "4",
        "YOLO_MODEL": str(artifacts / "yolov8n.pt"), "YOLO_DEVICE": "cpu",
        "YOLO_DETAIL_MODEL": str(artifacts / "yolov8s.pt"),
        "WORKER_MEMORY_LIMIT_MB": "8192", "DASHBOARD_MAX_FPS": "2",
        "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "DISK_MIN_FREE_GB": "0",
    })
    os.environ.update(environment)
    from app.config import get_settings
    get_settings.cache_clear()
    from app.db.engine import dispose, get_engine
    from app.db.tables import metadata
    from app.redis_client import close_redis, get_redis, HEATMAP_KEY_PREFIX

    def start(name, command, overrides=None):
        log = (artifacts / f"{name}.log").open("w", encoding="utf-8")
        files.append(log)
        process = subprocess.Popen(
            [sys.executable, *command], cwd=root, env={**environment, **(overrides or {})},
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        processes.append(process)
        return process

    report = {"source": args.url, "checks": {}, "limitations": [
        "Live scene has no labeled ground truth; precision and recall are not established.",
        "S3 delivery uses local Moto, not AWS; AWS permissions and expiry enforcement are not tested.",
        "YouTube embedded playback is separate; browser UI was not exercised by this harness.",
    ]}
    def check(name, ok, detail=None):
        report["checks"][name] = {"passed": bool(ok), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        # This URL is fixed to the dedicated disposable verification database.
        await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)

    start("storage", ["-m", "moto.server", "-H", "127.0.0.1", "-p", "19090"])
    async with httpx.AsyncClient(timeout=15) as client:
        for _ in range(60):
            if processes[-1].poll() is not None:
                raise RuntimeError("Storage emulator exited; inspect storage.log")
            try:
                if (await client.get("http://127.0.0.1:19090/")).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            await asyncio.sleep(1)
        from app.storage import _client
        s3 = _client(public=False)
        s3.create_bucket(Bucket="verification-snapshots")
        start("api", ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18765"])
        base = "http://127.0.0.1:18765"
        for _ in range(60):
            try:
                if (await client.get(base + "/api/health")).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            await asyncio.sleep(1)
        login = await client.post(base + "/api/auth/login", json={
            "email": environment["BOOTSTRAP_ADMIN_EMAIL"], "password": environment["BOOTSTRAP_ADMIN_PASSWORD"],
        })
        login.raise_for_status()
        token = login.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        added = await client.post(base + "/api/cameras", json={
            "name": "YouTube end-to-end verification", "source": args.url, "type": "youtube",
            "analysis_config": {"preset":args.preset,"tracker":args.tracker,"person_confidence":.4 if args.focused else .35,
                "regions":[{"x1":.38,"y1":.25,"x2":.68,"y2":.42}] if args.focused else []},
            "zones": [{"id": "test-zone", "name": "Whole frame test only", "polygon": [[0,0],[1,0],[1,1],[0,1]]},
                      {"id":"test-line","name":"Verification crossing line","line":[[.5,0],[.5,1]]}],
            "rules": [
                {"id": "test-intrusion", "type": "zone_intrusion", "zone_id": "test-zone", "object": "person", "severity": "warning", "cooldown_seconds": 15},
                {"id": "test-loiter", "type": "loitering", "object": "person", "threshold_seconds": 3, "severity": "info", "cooldown_seconds": 15},
                {"id": "test-car-intrusion", "type": "zone_intrusion", "zone_id": "test-zone", "object": "car", "severity": "warning", "cooldown_seconds": 15},
                {"id":"test-crossing","type":"line_crossing","zone_id":"test-line","object":"car","direction":"both","count_as":"crossing","cooldown_seconds":15,"min_frames":2},
            ],
        })
        added.raise_for_status()
        camera = added.json()
        cid = camera["id"]
        check("camera created through authenticated API", camera.get("youtube_id") is not None, cid)
        frames = alerts = 0
        first_frame = None
        max_people = 0
        started = time.monotonic()
        async with websockets.connect(f"ws://127.0.0.1:18765/api/ws?token={token}", max_size=4*1024*1024) as ws:
            await ws.send(json.dumps({"action": "subscribe", "camera_ids": [cid]}))
            pipeline = start("pipeline", ["-m", "app.pipeline.runner"], {"AGENT_MODE": "0", "PIPELINE_UPLOADS_ONLY": "1"})
            deadline = started + args.seconds
            while time.monotonic() < deadline:
                if pipeline.poll() is not None:
                    raise RuntimeError(f"Pipeline exited: {pipeline.returncode}; inspect pipeline.log")
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2)
                except TimeoutError:
                    continue
                message = json.loads(raw)
                if message.get("camera_id") != cid:
                    continue
                if message.get("type") == "frame":
                    frames += 1
                    first_frame = first_frame or round(time.monotonic() - started, 2)
                    max_people = max(max_people, message.get("in_frame", {}).get("person", 0))
                    (artifacts / "annotated-live-frame.jpg").write_bytes(base64.b64decode(message["image"]))
                elif message.get("type") == "incident":
                    alerts += 1
            check("annotated frames delivered over browser WebSocket", frames > 5, {"frames": frames, "first_frame_seconds": first_frame, "max_people_in_frame": max_people})
            check("rule alerts delivered over browser WebSocket", alerts > 0, alerts)

        response = await client.get(base + "/api/detections", params={"camera": cid, "limit": 1000})
        response.raise_for_status()
        detections = response.json()["items"]
        classes = sorted({d["object_type"] for d in detections})
        tracks = {}
        for det in detections:
            tracks[det["track_id"]] = tracks.get(det["track_id"], 0) + 1
        check("real model detections persisted and queryable", len(detections) > 20, {"returned": len(detections), "classes": classes})
        check("tracks persist across frames", max(tracks.values(), default=0) >= 3, {"track_ids": len(tracks), "longest_observed_track_frames": max(tracks.values(), default=0)})
        check("zone assignments persisted", any("test-zone" in d["zone_ids"] for d in detections))
        counts = (await client.get(base + "/api/counts")).json()
        check("live counts available to dashboard", cid in counts, counts.get(cid))
        cameras = (await client.get(base + "/api/cameras")).json()
        health = next(c["health"] for c in cameras if c["id"] == cid)
        check("analysis camera health online", health.get("online") and health.get("fps", 0) > 0, health)
        telemetry = next(c["analysis"] for c in cameras if c["id"] == cid)
        check("actual analysis telemetry available", telemetry.get("processed_frames",0)>5 and telemetry.get("inference_ms") is not None, telemetry)
        async with engine.connect() as conn:
            crossing_count=(await conn.execute(sa.text("SELECT COUNT(*) FROM crossing_events WHERE camera_id=:cid"),{"cid":cid})).scalar_one()
        report["live_crossing_events"]=crossing_count
        if crossing_count:
            check("live directional crossings persisted",True,crossing_count)
        incidents = (await client.get(base + "/api/incidents", params={"camera": cid})).json()
        check("real rules create stored incidents", bool(incidents), {"count": len(incidents), "types": sorted({i["incident_type"] for i in incidents})})
        snapshot_ok = False
        if incidents and incidents[0].get("snapshot_url"):
            # Separate client: never send the app JWT to object storage.
            async with httpx.AsyncClient(timeout=15) as storage_client:
                snapshot = await storage_client.get(incidents[0]["snapshot_url"])
                snapshot_ok = snapshot.status_code == 200 and snapshot.content.startswith(b"\xff\xd8")
                if snapshot_ok:
                    (artifacts / "incident-snapshot.jpg").write_bytes(snapshot.content)
        check("annotated snapshot uploaded and fetched via presigned URL", snapshot_ok)
        if counts.get(cid,{}).get("session",{}).get("person",0)>0:
            check("heatmap cells recorded", bool(await get_redis().hgetall(HEATMAP_KEY_PREFIX + cid)))
        else:
            report["limitations"].append("No sufficiently confirmed people in this live sample; live person heatmap not verified.")
        from app.analytics.jobs import aggregate_current_hour
        await aggregate_current_hour()
        stats = await client.get(base + f"/api/stats/{cid}")
        stats.raise_for_status()
        buckets = stats.json()["buckets"]
        check("hourly analytics available through dashboard API", bool(buckets) and any(b["footfall"] > 0 or b["vehicles"] for b in buckets), buckets)
        if args.reference_video:
            video=Path(args.reference_video).resolve()
            with video.open("rb") as upload:
                reference=await client.post(base+"/api/uploads",files={"file":(video.name,upload,"video/x-msvideo")},data={"name":"Reference crossing verification"},timeout=60)
            reference.raise_for_status()
            rid=reference.json()["camera_id"]
            configured=await client.patch(base+f"/api/cameras/{rid}",json={
                "analysis_config":{"preset":"fast","tracker":"centroid","confirmation_frames":2,"plate_reading":False},
                "zones":[{"id":"entry-line","line":[[.5,0],[.5,1]]}],
                "rules":[{"id":"entry","type":"line_crossing","object":"person","zone_id":"entry-line",
                          "direction":"positive","count_as":"entry","min_frames":2,"cooldown_seconds":60}]})
            configured.raise_for_status()
            end=time.monotonic()+60
            entries=0
            while time.monotonic()<end:
                async with engine.connect() as conn:
                    entries=(await conn.execute(sa.text("SELECT COUNT(*) FROM crossing_events WHERE camera_id=:cid AND count_as='entry'"),{"cid":rid})).scalar_one()
                if entries>=2:
                    break
                await asyncio.sleep(2)
            check("reference clip writes real entry crossings",entries>0,{"camera_id":rid,"entries":entries})
            async with engine.begin() as conn:
                # Hold inserts briefly for a consistent comparison of totals.
                await conn.execute(sa.text("LOCK TABLE crossing_events IN SHARE MODE"))
                entries=(await conn.execute(sa.text("SELECT COUNT(*) FROM crossing_events WHERE camera_id=:cid AND count_as='entry'"),{"cid":rid})).scalar_one()
                await aggregate_current_hour()
                reference_stats=(await client.get(base+f"/api/stats/{rid}")).json()["buckets"]
                footfall=sum(b["footfall"] for b in reference_stats)
                check("entry-based footfall equals persisted crossings",entries>0 and footfall==entries,{"entries":entries,"footfall":footfall})
            report["crossing_fixture"]="Local pedestrian reference video; live crossings are reported separately."
        report["elapsed_seconds"] = round(time.monotonic() - started, 1)
        report["ocr"] = {"plate_rows": sum(bool(d.get("plate_text")) for d in detections), "note": "No labeled plate sample; OCR accuracy is unverified."}
    await dispose()
    await close_redis()
    report["passed"] = all(c["passed"] for c in report["checks"].values())
    (artifacts / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.preview_seconds:
        print(f"Verification finished. Local test API remains available for {args.preview_seconds}s for browser QA.",flush=True)
        await asyncio.sleep(args.preview_seconds)
    return 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://www.youtube.com/watch?v=Q71sLS8h9a4")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--preset",choices=["fast","balanced","detail"],default="fast")
    parser.add_argument("--tracker",choices=["centroid","bytetrack","botsort"],default="centroid")
    parser.add_argument("--focused",action="store_true")
    parser.add_argument("--reference-video",type=Path)
    parser.add_argument("--preview-seconds",type=int,default=0)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    artifacts = root / ".e2e-live"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "media").mkdir(exist_ok=True)
    processes, files = [], []
    try:
        return asyncio.run(verify(args, root, artifacts, processes, files))
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    process.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=10)
        for file in files:
            file.close()


if __name__ == "__main__":
    sys.exit(main())

"""End-to-end pipeline test (Phases 2, 4, 5 acceptance).

Registers a looping file camera over the sample pedestrian video with a
low-threshold loitering rule, runs the real pipeline (YOLO + tracker + rules +
batched writes) for --seconds, then verifies:
  - detections were written to PostgreSQL in batches
  - person tracks got stable track ids
  - at least one loitering incident fired with an annotated snapshot
  - frames were published to the Redis frame channel
  - camera health in Redis reflects a live stream

Usage: python -m scripts.pipeline_e2e --video ..\\sample_videos\\vtest.avi --seconds 90
"""
import argparse
import asyncio
import os
import sys

import sqlalchemy as sa


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--seconds", type=int, default=90)
    args = ap.parse_args()

    video = os.path.abspath(args.video)
    assert os.path.isfile(video), f"missing video {video}"

    from app.db.engine import dispose, get_engine
    from app.db.tables import cameras, detections, incidents
    from app.ingestion.health import read_all_health
    from app.logging_config import setup_logging
    from app.pipeline.runner import Pipeline
    from app.redis_client import FRAME_CHANNEL, get_redis

    setup_logging("WARNING")
    cam_id = "e2e-test-cam"
    engine = get_engine()

    async with engine.begin() as conn:
        await conn.execute(sa.delete(incidents).where(incidents.c.camera_id == cam_id))
        await conn.execute(sa.delete(detections).where(detections.c.camera_id == cam_id))
        await conn.execute(sa.delete(cameras).where(cameras.c.id == cam_id))
        await conn.execute(sa.insert(cameras).values(
            id=cam_id, name="E2E Test", source=video, type="file", loop_file=True,
            zones=[], enabled=True,
            rules=[{
                "id": "e2e-loiter", "type": "loitering", "object": "person",
                "threshold_seconds": 8, "severity": "warning", "cooldown_seconds": 20,
            }],
        ))

    # count frame-channel messages while the pipeline runs
    frame_count = 0

    async def frame_counter():
        nonlocal frame_count
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(FRAME_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] == "message":
                frame_count += 1

    pipeline = Pipeline()
    counter_task = asyncio.create_task(frame_counter())
    run_task = asyncio.create_task(pipeline.run())
    print(f"pipeline running for {args.seconds}s ...", flush=True)
    await asyncio.sleep(args.seconds)

    pipeline.stop_event.set()
    for stream in pipeline.streams.values():
        stream.stop()
    run_task.cancel()
    counter_task.cancel()
    for t in (run_task, counter_task):
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    await pipeline.writer.stop()

    passed = failed = 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  PASS {name}")
        else:
            failed += 1
            print(f"  FAIL {name} {detail}")

    async with engine.connect() as conn:
        det_count = (await conn.execute(
            sa.select(sa.func.count()).select_from(detections)
            .where(detections.c.camera_id == cam_id))).scalar_one()
        track_count = (await conn.execute(
            sa.select(sa.func.count(sa.distinct(detections.c.track_id)))
            .where(detections.c.camera_id == cam_id,
                   detections.c.object_type == "person"))).scalar_one()
        incs = (await conn.execute(
            sa.select(incidents).where(incidents.c.camera_id == cam_id))).mappings().all()

    check("detections written", det_count > 50, f"got {det_count}")
    check("person tracks assigned", track_count >= 3, f"got {track_count}")
    check("loitering incident fired", len(incs) >= 1, "none")
    if incs:
        snap = incs[0]["snapshot_path"]
        from app.config import get_settings
        full = os.path.join(get_settings().media_root, snap) if snap else None
        check("snapshot saved", full and os.path.isfile(full), str(snap))
        # cooldown respected: fires spaced >= 20s
        times = sorted(i["ts"] for i in incs)
        gaps_ok = all((b - a).total_seconds() >= 19 for a, b in zip(times, times[1:]))
        check("cooldown respected", gaps_ok, str(times))
    check("frames published to Redis", frame_count > 20, f"got {frame_count}")

    health = await read_all_health([cam_id])
    check("camera health tracked", health[cam_id]["fps"] > 0, str(health))

    print(f"\ndetections={det_count} person_tracks={track_count} "
          f"incidents={len(incs)} frames_published={frame_count}")
    print(f"{passed} passed, {failed} failed")
    await dispose()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())

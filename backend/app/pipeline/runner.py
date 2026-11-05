"""Pipeline orchestrator process (the `inference` container entrypoint).

Responsibilities:
- Reconcile camera tasks against the cameras table on startup and every 15s
  (so admin edits take effect without restarts).
- Collect frames from all camera queues, batch up to INFERENCE_BATCH_SIZE,
  and run them through the ProcessPoolExecutor (YOLO loaded once per worker).
- Route results to per-camera processors (tracker, rules, OCR, writes).
- Run the alert dispatcher, analytics jobs, and resource guards.
- Replace crashed worker pools automatically without dropping cameras.
"""
import asyncio
import concurrent.futures
import logging
import os
import multiprocessing
import time

import cv2
import sqlalchemy as sa

from app.agent.runtime import run_agent_heartbeat, run_agent_stream
from app.alerts.dispatcher import run_dispatcher
from app.analytics.jobs import run_hourly_aggregation_loop, run_nightly_loop
from app.config import get_settings
from app.db.engine import dispose, get_engine
from app.db.tables import cameras as cameras_table, upload_jobs
from app.inference import worker as worker_mod
from app.inference.writer import DetectionWriter
from app.inference.options import resolve_options
from app.inference.telemetry import AnalysisTelemetry
from app.ingestion.health import CameraHealth
from app.ingestion.streams import CameraStream, Frame
from app.logging_config import setup_logging
from app.metrics import INFERENCE_LATENCY
from app.metrics import FRAMES_DROPPED
from app.pipeline.camera_worker import CameraProcessor
from app.pipeline.guards import run_resource_guards
from app.security import decrypt_source

log = logging.getLogger(__name__)

RECONCILE_INTERVAL = 15.0
BATCH_WAIT = 0.05  # max seconds to wait while assembling a batch


class Pipeline:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.streams: dict[str, CameraStream] = {}
        self.stream_tasks: dict[str, asyncio.Task] = {}
        self.processors: dict[str, CameraProcessor] = {}
        self.writer = DetectionWriter()
        self.pool: concurrent.futures.ProcessPoolExecutor | None = None
        self.stop_event = asyncio.Event()
        self._batch_cursor = 0

    # --- worker pool ---

    def _make_pool(self) -> concurrent.futures.ProcessPoolExecutor:
        s = self.settings
        return concurrent.futures.ProcessPoolExecutor(
            mp_context=multiprocessing.get_context("spawn"),
            max_workers=s.inference_workers,
            initializer=worker_mod.init_worker,
            initargs=(s.yolo_model, s.yolo_device, s.person_confidence,
                      s.vehicle_confidence, s.inference_max_dim),
        )

    async def _infer(self, jpeg_frames: list[bytes], options=None) -> list[list[dict]]:
        """Run a batch in the pool; rebuild the pool once if it broke (worker crash)."""
        loop = asyncio.get_running_loop()
        for attempt in (1, 2):
            if self.pool is None:
                self.pool = self._make_pool()
            try:
                t0 = time.monotonic()
                result = await asyncio.wait_for(loop.run_in_executor(
                    self.pool, worker_mod.detect_batch, jpeg_frames, options
                ),timeout=self.settings.inference_timeout_secs)
                INFERENCE_LATENCY.observe(time.monotonic() - t0)
                return result
            except (concurrent.futures.process.BrokenProcessPool, TimeoutError):
                log.error("inference pool broke (attempt %d), rebuilding", attempt)
                # Terminate only this pipeline's owned workers. Cancelling a future
                # alone cannot stop a stuck native inference call.
                processes = list((getattr(self.pool,"_processes",None) or {}).values())
                self.pool.shutdown(wait=False, cancel_futures=True)
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                self.pool = None
        raise RuntimeError("Inference worker failed to initialize")

    # --- camera reconciliation ---

    async def _camera_rows(self) -> list[dict] | None:
        """Camera source rows for reconcile.

        Normal mode reads the local cameras table. Agent mode pulls the set from
        the cloud (``GET /agent/v1/config``) so a site box is driven entirely by
        the cloud control plane. Returns ``None`` when the cloud is unreachable,
        which tells the caller to keep the current streams running unchanged.
        """
        if self.settings.agent_mode:
            from app.agent.client import get_agent_client

            try:
                cfg = await get_agent_client().get_config()
            except Exception:
                log.exception("agent config fetch failed; keeping current cameras")
                return None
            rows = cfg.get("cameras") or []
            log.info("agent config version=%s cameras=%d", cfg.get("config_version"), len(rows))
            return rows

        engine = get_engine()
        query = sa.select(cameras_table)
        if self.settings.pipeline_uploads_only:
            query = query.where(sa.or_(
                cameras_table.c.id.in_(sa.select(upload_jobs.c.camera_id)),
                cameras_table.c.type == "youtube",
            ))
        async with engine.connect() as conn:
            rows = (await conn.execute(query)).mappings().all()
        return list(rows)

    async def reconcile(self) -> None:
        rows = await self._camera_rows()
        if rows is None:
            return

        enabled = {r["id"]: r for r in rows if r["enabled"]}

        # stop removed/disabled cameras
        for cid in list(self.streams):
            row = enabled.get(cid)
            try:
                source = decrypt_source(row["source"]) if row else None
            except RuntimeError:
                log.exception("cannot decrypt changed source", extra={"camera_id": cid})
                continue
            changed = row and (
                self.streams[cid].source != source
                or self.streams[cid].source_type != row["type"]
                or self.streams[cid].loop_file != bool(row["loop_file"])
                or self.streams[cid].refresh_secs != float(row["refresh_secs"] or 2)
                or self.processors[cid].analysis_options != resolve_options(row.get("analysis_config"))
            )
            if cid not in enabled or changed:
                log.info("stopping camera stream", extra={"camera_id": cid})
                self.streams[cid].stop()
                self.stream_tasks[cid].cancel()
                del self.streams[cid], self.stream_tasks[cid]
                self.processors.pop(cid, None)

        # start new cameras, refresh config on existing ones
        for cid, row in enabled.items():
            zones = row["zones"] or []
            rules = row["rules"] or []
            if cid in self.streams:
                self.processors[cid].update_config(zones, rules)
                # restart the stream task if it died unexpectedly
                if self.stream_tasks[cid].done():
                    log.warning("stream task dead, restarting", extra={"camera_id": cid})
                    self.stream_tasks[cid] = asyncio.create_task(self.streams[cid].run())
                continue
            if len(self.streams) >= self.settings.max_cameras_per_node:
                log.warning("MAX_CAMERAS_PER_NODE reached, skipping %s", cid)
                continue
            try:
                source = decrypt_source(row["source"])
            except RuntimeError:
                log.exception("cannot decrypt source", extra={"camera_id": cid})
                continue
            stream = CameraStream(
                camera_id=cid,
                source=source,
                source_type=row["type"],
                refresh_secs=float(row["refresh_secs"] or 2.0),
                loop_file=bool(row["loop_file"]),
                health=CameraHealth(camera_id=cid),
            )
            self.streams[cid] = stream
            self.processors[cid] = CameraProcessor(
                cid, zones, rules, self.writer, source_type=row["type"],
                analysis_config=row.get("analysis_config"),
            )
            self.processors[cid].telemetry = AnalysisTelemetry(cid, self.processors[cid].analysis_options)
            stream.analysis_health = self.processors[cid].telemetry
            await stream.analysis_health.flush(force=True)
            self.stream_tasks[cid] = asyncio.create_task(stream.run())
            log.info("camera stream started", extra={"camera_id": cid})

    async def _reconcile_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await self.reconcile()
            except Exception:
                log.exception("reconcile failed")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=RECONCILE_INTERVAL)
            except TimeoutError:
                pass

    # --- inference loop ---

    def _collect_batch(self) -> list[Frame]:
        """Grab at most one pending frame per camera, up to the batch size."""
        batch: list[Frame] = []
        ids = list(self.streams)
        if not ids:
            return batch
        ordered = ids[self._batch_cursor:] + ids[:self._batch_cursor]
        self._batch_cursor = (self._batch_cursor + self.settings.inference_batch_size) % len(ids)
        for cid in ordered:
            stream = self.streams[cid]
            if len(batch) >= self.settings.inference_batch_size:
                break
            try:
                frame = stream.queue.get_nowait()
                # A camera never consumes old backlog while fresh frames wait.
                while not stream.queue.empty():
                    frame = stream.queue.get_nowait()
                    if stream.health:
                        stream.health.frames_dropped += 1
                    FRAMES_DROPPED.labels(camera_id=cid).inc()
                if time.time()-frame.ts <= self.settings.max_analysis_frame_age_secs:
                    batch.append(frame)
                elif stream.health:
                    stream.health.frames_dropped += 1
                    FRAMES_DROPPED.labels(camera_id=cid).inc()
            except asyncio.QueueEmpty:
                continue
        return batch

    async def _inference_loop(self) -> None:
        if os.environ.get("INFERENCE_DEBUG_STACKS") == "1":
            import faulthandler
            faulthandler.dump_traceback_later(20,repeat=True)
        quality = [cv2.IMWRITE_JPEG_QUALITY, 85]
        while not self.stop_event.is_set():
            batch = self._collect_batch()
            if not batch:
                await asyncio.sleep(BATCH_WAIT)
                continue
            jpegs: list[bytes] = []
            for frame in batch:
                ok, buf = cv2.imencode(".jpg", frame.image, quality)
                jpegs.append(buf.tobytes() if ok else b"")
            t0 = time.monotonic()
            processors = {frame.camera_id:self.processors.get(frame.camera_id) for frame in batch}
            try:
                results = await self._infer(jpegs, [processors[f.camera_id].analysis_options for f in batch])
            except Exception as exc:
                log.exception("inference failed")
                for frame in batch:
                    proc = processors[frame.camera_id]
                    if self.processors.get(frame.camera_id) is not proc:
                        continue
                    telemetry = proc.telemetry
                    telemetry.state, telemetry.error = "error", type(exc).__name__
                    await telemetry.flush(force=True)
                await asyncio.sleep(1)
                continue
            inference_ms = (time.monotonic()-t0)*1000
            for frame, detections in zip(batch, results):
                proc = self.processors.get(frame.camera_id)
                if proc is None or proc is not processors[frame.camera_id]:
                    continue
                try:
                    await proc.process(frame.image, detections, frame.ts)
                    proc.telemetry.dropped = self.streams[frame.camera_id].health.frames_dropped
                    proc.telemetry.queue_depth = self.streams[frame.camera_id].queue.qsize()
                    await proc.telemetry.record(frame.ts, inference_ms)
                except Exception:
                    proc.telemetry.state, proc.telemetry.error = "error", "Frame processing failed"
                    await proc.telemetry.flush(force=True)
                    log.exception("frame processing failed",
                                  extra={"camera_id": frame.camera_id})

    # --- lifecycle ---

    async def run(self) -> None:
        await self.writer.start()
        self.pool = self._make_pool()
        tasks = [
            asyncio.create_task(self._reconcile_loop(), name="reconcile"),
            asyncio.create_task(self._inference_loop(), name="inference"),
            asyncio.create_task(run_resource_guards(self.stop_event), name="guards"),
        ]
        if os.environ.get("INFERENCE_DEBUG_STACKS") == "1":
            async def diagnose():
                while not self.stop_event.is_set():
                    await asyncio.sleep(10)
                    for task in [tasks[1], self.writer._task]:
                        chain=[]
                        coroutine=task.get_coro()
                        while coroutine is not None:
                            frame=getattr(coroutine,"cr_frame",None) or getattr(coroutine,"gi_frame",None)
                            if frame:
                                chain.append(f"{frame.f_code.co_name}:{frame.f_lineno}")
                            coroutine=getattr(coroutine,"cr_await",None) or getattr(coroutine,"gi_yieldfrom",None)
                        log.warning("task %s done=%s awaiting=%s",task.get_name(),task.done(),chain)
            tasks.append(asyncio.create_task(diagnose(),name="diagnostics"))
        if self.settings.agent_mode:
            # The site agent keeps no local Postgres/Redis. Alert fan-out,
            # analytics rollups and nightly maintenance are cloud-side jobs;
            # only the live frame uplink and the health heartbeat run here.
            tasks.append(
                asyncio.create_task(
                    run_agent_heartbeat(self.streams, self.stop_event), name="agent-heartbeat"
                )
            )
            tasks.append(
                asyncio.create_task(run_agent_stream(self.stop_event), name="agent-stream")
            )
        else:
            tasks.append(
                asyncio.create_task(run_dispatcher(self.stop_event), name="alert-dispatcher")
            )
            tasks.append(
                asyncio.create_task(run_hourly_aggregation_loop(self.stop_event), name="analytics")
            )
            tasks.append(
                asyncio.create_task(run_nightly_loop(self.stop_event), name="nightly")
            )
        try:
            await asyncio.gather(*tasks)
        finally:
            self.stop_event.set()
            for stream in self.streams.values():
                stream.stop()
            for task in [*self.stream_tasks.values(), *tasks]:
                task.cancel()
            await self.writer.stop()
            if self.settings.pipeline_uploads_only:
                from app.agent.client import get_agent_client

                await get_agent_client().stop_outbox()
            if self.pool:
                self.pool.shutdown(wait=False, cancel_futures=True)
            await dispose()


def main() -> None:
    setup_logging()
    log.info("starting Iso Safe pipeline")
    pipeline = Pipeline()
    try:
        asyncio.run(pipeline.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

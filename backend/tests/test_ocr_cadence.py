"""A slow plate reader must not stall detection/alerts, or misassign its result."""
import asyncio
from types import SimpleNamespace

import numpy as np

from app.pipeline import camera_worker


async def test_slow_ocr_does_not_block_frames_and_result_matches_track(monkeypatch):
    release = asyncio.Event()
    calls = []
    rows = []

    async def read(*args):
        calls.append(args)
        await release.wait()
        return "ABC123", 0.9

    async def add(*args):
        rows.append(args)

    async def noop(*args):
        pass

    monkeypatch.setattr(camera_worker, "read_plate", read)
    monkeypatch.setattr(camera_worker, "get_settings", lambda: SimpleNamespace(
        ocr_every_n_frames=5, plate_confidence=.2, plate_consensus_reads=3,
    ))
    processor = camera_worker.CameraProcessor("test", [], [], SimpleNamespace(add=add))
    monkeypatch.setattr(processor, "_update_heatmap", noop)
    monkeypatch.setattr(processor, "_publish", noop)
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    detections = [{"object_type": "car", "bbox": [0, 0, .8, .8], "confidence": .9}]
    for i in range(1, 11):
        await asyncio.wait_for(processor.process(image, detections, i*.1), timeout=1)
    await asyncio.sleep(0)  # Allow the queued OCR coroutine to start.
    assert len(rows) == 10 and len(calls) == 1
    release.set()
    await processor._ocr_task
    await processor.process(image, detections, 1.1)
    assert rows[-1][-2:] == (None, None)
    for i in range(12,24):
        await processor.process(image, detections, i*.1)
        await asyncio.sleep(0)
    recognized = [row for row in rows if row[-2]]
    assert len(recognized) == 1
    assert recognized[0][-2:] == ("ABC123", .9)
    assert recognized[0][4] == 1

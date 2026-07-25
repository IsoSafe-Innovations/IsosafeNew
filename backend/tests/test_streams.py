"""Phase 2 acceptance-adjacent tests: bounded queue drop-oldest behavior and
file stream lifecycle without a real camera."""
import asyncio

import numpy as np
import pytest

from app.ingestion.streams import CameraStream, Frame


def make_stream(**kwargs) -> CameraStream:
    defaults = dict(camera_id="cam-test", source="unused", source_type="file")
    defaults.update(kwargs)
    return CameraStream(**defaults)


@pytest.mark.asyncio
async def test_drop_oldest_when_full():
    stream = make_stream()
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    for _ in range(5):
        stream._enqueue(img)
    assert stream.queue.qsize() == 2  # bounded at 2
    first: Frame = stream.queue.get_nowait()
    second: Frame = stream.queue.get_nowait()
    # the two newest frames survived (seq 3, 4)
    assert first.seq == 3
    assert second.seq == 4


@pytest.mark.asyncio
async def test_unknown_source_type_returns():
    stream = make_stream(source_type="carrier_pigeon")
    await asyncio.wait_for(stream.run(), timeout=2)  # returns, no exception


@pytest.mark.asyncio
async def test_stop_terminates_loop():
    stream = make_stream(source_type="rtsp", source="rtsp://192.0.2.1/none")
    task = asyncio.create_task(stream.run())
    await asyncio.sleep(0.2)
    stream.stop()
    await asyncio.wait_for(task, timeout=40)  # exits at next backoff check

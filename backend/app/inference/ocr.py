"""EasyOCR plate reading on vehicle crops.

Runs in a thread executor (EasyOCR is blocking). Latin alphanumeric allowlist,
per-track dedup: same plate on the same track within 60s is skipped.
"""
import asyncio
import logging
import re

import numpy as np

log = logging.getLogger(__name__)

ALLOWLIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
PLATE_RE = re.compile(r"^[A-Z0-9]{4,10}$")
DEDUP_SECONDS = 60.0

_reader = None
_lock = asyncio.Lock()


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr

        _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _reader


def _read_plate_sync(crop: np.ndarray, min_conf: float) -> tuple[str, float] | None:
    reader = _get_reader()
    try:
        results = reader.readtext(crop, allowlist=ALLOWLIST, detail=1)
    except Exception:
        log.exception("OCR failed")
        return None
    best: tuple[str, float] | None = None
    for _bbox, text, conf in results:
        text = re.sub(r"[^A-Z0-9]", "", text.upper())
        if not PLATE_RE.match(text):
            continue
        if conf >= min_conf and (best is None or conf > best[1]):
            best = (text, float(conf))
    return best


async def read_plate(
    image: np.ndarray, bbox: list[float], min_conf: float
) -> tuple[str, float] | None:
    """Crop the vehicle region (normalized bbox) and OCR it."""
    h, w = image.shape[:2]
    x1 = max(0, int(bbox[0] * w))
    y1 = max(0, int(bbox[1] * h))
    x2 = min(w, int(bbox[2] * w))
    y2 = min(h, int(bbox[3] * h))
    if x2 - x1 < 40 or y2 - y1 < 20:
        return None
    crop = image[y1:y2, x1:x2]
    loop = asyncio.get_running_loop()
    async with _lock:  # EasyOCR reader is not thread-safe across concurrent calls
        return await loop.run_in_executor(None, _read_plate_sync, crop, min_conf)

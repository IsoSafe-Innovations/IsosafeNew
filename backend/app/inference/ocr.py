"""EasyOCR plate reading on vehicle crops.

Runs in a thread executor (EasyOCR is blocking). Latin alphanumeric allowlist,
per-track dedup: same plate on the same track within 60s is skipped.
"""
import asyncio
import logging
import re

import numpy as np

from app.config import get_settings
from app.inference.plates import locate_plate

log = logging.getLogger(__name__)

ALLOWLIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
PLATE_RE = re.compile(r"^[A-Z0-9]{4,10}$")
DEDUP_SECONDS = 60.0

_reader = None
_reader_failed = False
_lock = asyncio.Lock()


def _get_reader():
    global _reader, _reader_failed
    if _reader_failed:
        return None
    if _reader is None:
        import easyocr
        import os
        import torch
        torch.set_num_threads(get_settings().inference_threads)

        try:
            _reader = easyocr.Reader(["en"], gpu=False, verbose=False,
                model_storage_directory=os.environ.get("OCR_MODEL_DIR") or None)
        except Exception:
            log.exception("EasyOCR init failed — plate reading disabled")
            _reader_failed = True
            return None
    return _reader


def _read_plate_sync(crop: np.ndarray, min_conf: float) -> tuple[str, float] | None:
    reader = _get_reader()
    if reader is None:
        return None
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
    def recognize():
        settings = get_settings()
        crop, _ = locate_plate(image, bbox, settings.plate_min_width, settings.plate_min_sharpness)
        if crop is None:
            return None
        return _read_plate_sync(crop, max(.65, min_conf))
    loop = asyncio.get_running_loop()
    async with _lock:  # EasyOCR reader is not thread-safe across concurrent calls
        return await loop.run_in_executor(None, recognize)

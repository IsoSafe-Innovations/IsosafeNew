"""Bounded model cache and per-camera inference, shared with accuracy benchmarks."""
import os
from collections import OrderedDict

import cv2
import numpy as np

from app.inference.detection_geometry import crop_windows, suppress

KEEP_CLASSES = {0: "person", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck", 24: "backpack", 28: "suitcase"}
VEHICLE_TYPES = {"car", "motorcycle", "bus", "truck"}
BAG_TYPES = {"backpack", "suitcase"}
_model = None
_models = OrderedDict()
_thresholds = {}
_max_dim = 640
_device = "cpu"


def _load_model(path):
    from ultralytics import YOLO
    if path not in _models:
        model = YOLO(path)
        model.to(_device)
        _models[path] = model
        while len(_models) > 2:
            _models.popitem(last=False)
    _models.move_to_end(path)
    return _models[path]


def init_worker(model_path, device, person_conf, vehicle_conf, max_dim):
    global _model, _thresholds, _max_dim, _device
    import torch
    if os.environ.get("INFERENCE_DEBUG_STACKS") == "1":
        import faulthandler
        faulthandler.dump_traceback_later(20,repeat=True)
    from app.config import get_settings
    os.environ.setdefault("YOLO_VERBOSE", "false")
    torch.set_num_threads(get_settings().inference_threads)
    cv2.setNumThreads(1)
    _device = device
    _thresholds = {"person": person_conf, "vehicle": vehicle_conf}
    _max_dim = max_dim
    _model = _load_model(model_path)
    _model.predict(np.zeros((max_dim, max_dim, 3), dtype=np.uint8), imgsz=max_dim, verbose=False)


def _resize(image):
    h, w = image.shape[:2]
    scale = min(1., _max_dim / max(h, w))
    return (cv2.resize(image, (int(w*scale), int(h*scale))) if scale < 1 else image), scale


def detect_batch(jpeg_frames, options=None):
    from app.config import get_settings
    assert _model is not None, "worker not initialized"
    options = options or [{} for _ in jpeg_frames]
    if len(options) != len(jpeg_frames):
        raise ValueError("One options object is required per frame")
    # Group frames with identical model/input settings for a single batched call.
    groups = {}
    output = [[] for _ in jpeg_frames]
    for index, (buf, config) in enumerate(zip(jpeg_frames, options)):
        image = cv2.imdecode(np.frombuffer(buf, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            continue
        h, w = image.shape[:2]
        path = config.get("model") or get_settings().yolo_model
        size = config.get("input_size") or _max_dim
        key = (path, size)
        for x1, y1, x2, y2 in crop_windows(w, h, config):
            groups.setdefault(key, []).append((index, image[y1:y2, x1:x2], (x1,y1,x2,y2), (w,h), config))
    for (path, size), items in groups.items():
        model = _load_model(path)
        # Small chunks bound memory even when several cameras use tiled inference.
        for offset in range(0, len(items), 4):
            chunk = items[offset:offset+4]
            results = model.predict([i[1] for i in chunk], imgsz=size, conf=.1, classes=list(KEEP_CLASSES), verbose=False)
            for result, (index, image, window, dimensions, config) in zip(results, chunk):
                if result.boxes is None:
                    continue
                xoff, yoff, _, _ = window
                width, height = dimensions
                for box in result.boxes:
                    name = KEEP_CLASSES.get(int(box.cls[0]))
                    if not name:
                        continue
                    confidence = float(box.conf[0])
                    threshold = config.get("person_confidence", _thresholds["person"]) if name == "person" else config.get("vehicle_confidence", _thresholds["vehicle"])
                    # Low-score detections can recover existing ByteTrack tracks;
                    # they cannot create new confirmed tracks or fire alerts alone.
                    eligible = confidence >= threshold
                    if not eligible and config.get("tracker", "centroid") == "centroid":
                        continue
                    x1,y1,x2,y2 = box.xyxy[0].tolist()
                    output[index].append({"object_type": name, "confidence": round(confidence,4), "confirmed": eligible,
                        "bbox": [max(0., (x1+xoff)/width), max(0., (y1+yoff)/height), min(1., (x2+xoff)/width), min(1., (y2+yoff)/height)]})
    return [suppress(detections) for detections in output]

"""YOLO inference worker. Runs inside a ProcessPoolExecutor process.

The model is loaded once per process at initialization. The main process sends
batches of (camera_id, jpeg bytes); the worker returns detection lists per frame.
Batching frames across cameras into a single YOLO call is the largest throughput
win on GPU, and still helps on CPU.
"""
import os

import cv2
import numpy as np

# COCO classes we keep: person, car, motorcycle, bus, truck, backpack, suitcase
KEEP_CLASSES = {0: "person", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck",
                24: "backpack", 28: "suitcase"}
VEHICLE_TYPES = {"car", "motorcycle", "bus", "truck"}
BAG_TYPES = {"backpack", "suitcase"}

_model = None
_thresholds: dict[str, float] = {}
_max_dim = 640


def init_worker(model_path: str, device: str, person_conf: float, vehicle_conf: float,
                max_dim: int) -> None:
    """ProcessPoolExecutor initializer: load YOLO once per worker process."""
    global _model, _thresholds, _max_dim
    os.environ.setdefault("YOLO_VERBOSE", "false")
    from ultralytics import YOLO

    _model = YOLO(model_path)
    _model.to(device)
    _thresholds = {"person": person_conf, "vehicle": vehicle_conf}
    _max_dim = max_dim
    # Warm up so the first real frame isn't slow
    _model.predict(np.zeros((max_dim, max_dim, 3), dtype=np.uint8), verbose=False)


def _resize(image: np.ndarray) -> tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    scale = min(1.0, _max_dim / max(h, w))
    if scale < 1.0:
        image = cv2.resize(image, (int(w * scale), int(h * scale)))
    return image, scale


def detect_batch(jpeg_frames: list[bytes]) -> list[list[dict]]:
    """Decode JPEGs, run one batched YOLO call, return normalized detections per frame.

    bbox coordinates are normalized to [0, 1] so they are resolution-independent.
    """
    global _model
    assert _model is not None, "worker not initialized"

    images = []
    for buf in jpeg_frames:
        arr = np.frombuffer(buf, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            img = np.zeros((64, 64, 3), dtype=np.uint8)
        img, _ = _resize(img)
        images.append(img)

    min_conf = min(_thresholds.values()) if _thresholds else 0.2
    results = _model.predict(images, verbose=False, conf=min_conf)

    out: list[list[dict]] = []
    for img, res in zip(images, results):
        h, w = img.shape[:2]
        dets: list[dict] = []
        if res.boxes is not None:
            for box in res.boxes:
                cls_id = int(box.cls[0])
                if cls_id not in KEEP_CLASSES:
                    continue
                obj_type = KEEP_CLASSES[cls_id]
                conf = float(box.conf[0])
                threshold = (
                    _thresholds["person"] if obj_type == "person"
                    else _thresholds["vehicle"]
                )
                if conf < threshold:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                dets.append(
                    {
                        "object_type": obj_type,
                        "confidence": round(conf, 4),
                        "bbox": [
                            round(x1 / w, 4), round(y1 / h, 4),
                            round(x2 / w, 4), round(y2 / h, 4),
                        ],
                    }
                )
        out.append(dets)
    return out

"""Prometheus metrics shared across the app."""
from prometheus_client import Counter, Gauge, Histogram

FRAMES_PROCESSED = Counter(
    "isosafe_frames_processed_total", "Frames run through inference", ["camera_id"]
)
FRAMES_DROPPED = Counter(
    "isosafe_frames_dropped_total", "Frames dropped due to full queue", ["camera_id"]
)
INFERENCE_LATENCY = Histogram(
    "isosafe_inference_latency_seconds",
    "YOLO inference latency per batch",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)
QUEUE_DEPTH = Gauge("isosafe_frame_queue_depth", "Pending frames per camera", ["camera_id"])
DETECTIONS_WRITTEN = Counter("isosafe_detections_written_total", "Detection rows inserted")
WS_CLIENTS = Gauge("isosafe_ws_clients", "Connected WebSocket clients")
RULE_EVALUATIONS = Counter(
    "isosafe_rule_evaluations_total", "Rule evaluations", ["rule_type"]
)
INCIDENTS_FIRED = Counter(
    "isosafe_incidents_total", "Incidents created", ["incident_type", "severity"]
)
ALERT_DISPATCH_LATENCY = Histogram(
    "isosafe_alert_dispatch_latency_seconds",
    "Detection-to-dispatch latency",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)
CAMERA_FPS = Gauge("isosafe_camera_fps", "Achieved processed FPS per camera", ["camera_id"])
STREAM_RECONNECTS = Counter(
    "isosafe_stream_reconnects_total", "Stream reconnect attempts", ["camera_id"]
)

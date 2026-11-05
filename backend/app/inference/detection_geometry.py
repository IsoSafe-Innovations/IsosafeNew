"""Crop remapping and class-aware suppression, shared by live and benchmark runs."""


def iou(a, b):
    w = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = w * h
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union > 0 else 0


def suppress(detections, threshold=.5):
    kept = []
    for detection in sorted(detections, key=lambda d: -d["confidence"]):
        if not any(detection["object_type"] == d["object_type"] and iou(detection["bbox"], d["bbox"]) > threshold for d in kept):
            kept.append(detection)
        if len(kept) >= 300:
            break
    return kept


def crop_windows(width, height, options):
    windows = [(0, 0, width, height)]
    if options.get("tiled"):
        # Four overlapping crops preserve detail; full frame retains large objects.
        for y in (0, .4):
            for x in (0, .4):
                windows.append((int(x*width), int(y*height), min(width, int((x+.6)*width)), min(height, int((y+.6)*height))))
    for region in options.get("regions", []):
        windows.append((int(region["x1"]*width), int(region["y1"]*height), int(region["x2"]*width), int(region["y2"]*height)))
    return [w for w in dict.fromkeys(windows) if w[2] > w[0] and w[3] > w[1]]

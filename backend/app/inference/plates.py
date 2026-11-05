"""Plate candidate localization, quality gating, and temporal consensus.

The default localizer is geometric and deliberately abstains on distant/blurred
plates. A deployment can supply a trained plate detector with PLATE_MODEL.
"""
import os
import re
from collections import Counter, deque

import cv2
import numpy as np

_detector = None


def locate_plate(image, bbox, min_width=64, min_sharpness=60):
    h,w = image.shape[:2]
    x1,y1,x2,y2 = bbox
    vehicle = image[max(0,int(y1*h)):min(h,int(y2*h)), max(0,int(x1*w)):min(w,int(x2*w))]
    if vehicle.size == 0 or vehicle.shape[1] < min_width:
        return None, "insufficient_detail"
    gray = cv2.cvtColor(vehicle, cv2.COLOR_BGR2GRAY)
    candidates = []
    model_path = os.environ.get("PLATE_MODEL", "")
    if model_path:
        global _detector
        if _detector is None:
            from ultralytics import YOLO
            _detector = YOLO(model_path)
        for result in _detector.predict(vehicle, conf=.5, verbose=False):
            for box in result.boxes:
                a,b,c,d = [int(v) for v in box.xyxy[0].tolist()]
                candidates.append((a,b,c-a,d-b))
    else:
        edges = cv2.Canny(gray, 60, 180)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3,3),np.uint8))
        contours,_ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x,y,cw,ch = cv2.boundingRect(contour)
            if cw >= min_width and ch >= 16 and 2 <= cw/ch <= 6.5 and cw*ch < .35*gray.size:
                candidates.append((x,y,cw,ch))
    best, best_quality = None, 0
    for x,y,cw,ch in candidates:
        crop = vehicle[max(0,y):y+ch, max(0,x):x+cw]
        if crop.size == 0 or cw < min_width or ch < 16:
            continue
        quality = float(cv2.Laplacian(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
        if quality >= min_sharpness and quality > best_quality:
            best, best_quality = crop.copy(), quality
    return best, "candidate" if best is not None else "insufficient_detail"


class PlateConsensus:
    def __init__(self, reads=3, max_age=10):
        self.reads, self.max_age = reads, max_age
        self.samples = deque(maxlen=10)

    def add(self, text, confidence, ts):
        text = re.sub(r"[^A-Z0-9]", "", text.upper())
        # Require both letters and numbers; generic signs/vehicle branding abstain.
        if not 4 <= len(text) <= 10 or not any(c.isdigit() for c in text) or not any(c.isalpha() for c in text) or confidence < .65:
            return None
        self.samples = deque((s for s in self.samples if ts-s[2] <= self.max_age), maxlen=10)
        if self.samples and self.samples[-1][2] == ts:
            return None
        self.samples.append((text,confidence,ts))
        counts = Counter(s[0] for s in self.samples)
        winner,count = counts.most_common(1)[0]
        if count >= self.reads and count/len(self.samples) >= .65:
            return winner, sum(s[1] for s in self.samples if s[0]==winner)/count
        return None

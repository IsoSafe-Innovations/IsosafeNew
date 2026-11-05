"""ByteTrack/BoT-SORT adapters retaining the application's Track/rule contract."""
import itertools
import time
from types import SimpleNamespace

import numpy as np

from app.inference.detection_geometry import iou
from app.inference.tracker import Track, _centroid
from app.inference.worker import KEEP_CLASSES


class MotionTracker:
    def __init__(self, kind="bytetrack", confirmation_frames=3):
        from ultralytics.trackers.byte_tracker import BYTETracker
        from ultralytics.trackers.bot_sort import BOTSORT
        from ultralytics.trackers.basetrack import BaseTrack

        args = SimpleNamespace(track_high_thresh=.25, track_low_thresh=.1,
            new_track_thresh=.25, track_buffer=30, match_thresh=.8, fuse_score=True,
            gmc_method="none", proximity_thresh=.5, appearance_thresh=.25,
            with_reid=False, model="auto")
        previous_count = BaseTrack._count
        self.engine = (BOTSORT if kind == "botsort" else BYTETracker)(args)
        BaseTrack._count = max(previous_count, BaseTrack._count)
        self.tracks = {}
        self.session_counts = {}
        self.confirmation_frames = confirmation_frames
        self._keys = {}
        self._ids = itertools.count(1)
        self._counted = set()

    def update(self, detections, now=None):
        from ultralytics.engine.results import Boxes

        now = time.time() if now is None else now
        names = {name: key for key, name in KEEP_CLASSES.items()}
        data = np.array([[*(np.array(d["bbox"])*1000), d["confidence"], names[d["object_type"]]] for d in detections], dtype=np.float32).reshape(-1,6)
        results = self.engine.update(Boxes(data, (1000,1000)))
        matches = [None] * len(detections)
        used = set()
        for row in results:
            name = KEEP_CLASSES.get(int(row[6]))
            bbox = (np.array(row[:4])/1000).tolist()
            candidates = [(iou(bbox,d["bbox"]), i) for i,d in enumerate(detections)
                          if i not in used and d["object_type"] == name]
            if not candidates:
                continue
            overlap, index = max(candidates)
            if overlap < .1:
                continue
            used.add(index)
            key = (int(row[4]), name)
            tid = self._keys.get(key)
            det = detections[index]
            if tid is None:
                if not det.get("confirmed", True):
                    continue
                tid = next(self._ids)
                self._keys[key] = tid
            track = self.tracks.get(tid)
            if track is None:
                track = Track(tid, name, _centroid(det["bbox"]), det["bbox"], now, now, hits=0)
                self.tracks[tid] = track
            # Detection order may change; association is geometric, never zip order.
            track.bbox = det["bbox"]
            track.centroid = _centroid(track.bbox)
            track.observation_gap = now - track.last_seen
            track.last_seen = now
            track.frames_missing = 0
            track.hits += 1
            track.confident = det.get("confirmed", True)
            track.history.append((now, track.centroid))
            det["track_id"] = tid
            matches[index] = track
            if tid not in self._counted and track.hits >= self.confirmation_frames:
                self.session_counts[name] = self.session_counts.get(name, 0) + 1
                self._counted.add(tid)
        visible = {t.track_id for t in matches if t is not None}
        for tid in list(self.tracks):
            if tid not in visible:
                self.tracks[tid].frames_missing += 1
                if self.tracks[tid].frames_missing > 30:
                    del self.tracks[tid]
        # Expired upstream IDs cannot be reused; trim metadata as well as tracks.
        self._keys = {key: tid for key,tid in self._keys.items() if tid in self.tracks}
        self._counted.intersection_update(self.tracks)
        return matches

    def active_tracks(self, object_type=None):
        return [t for t in self.tracks.values() if not t.frames_missing and (object_type is None or t.object_type == object_type)]


def make_tracker(options):
    if options.get("tracker", "centroid") == "centroid":
        from app.inference.tracker import CentroidTracker
        return CentroidTracker(options.get("confirmation_frames", 3))
    return MotionTracker(options["tracker"], options.get("confirmation_frames", 3))

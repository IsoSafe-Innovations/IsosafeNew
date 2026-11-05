"""Centroid tracker, one instance per camera, running in the main process.

Matches detections to existing tracks by Euclidean distance with a max-distance
gate. Position history is capped at 300 entries; tracks unseen for 30 processed
frames are expired. Unique session counts increment once per new track.
"""
import itertools
import math
import time
from collections import deque
from dataclasses import dataclass, field

MAX_HISTORY = 300
EXPIRE_AFTER_FRAMES = 30
MAX_MATCH_DISTANCE = 0.12  # normalized units (bbox coords are 0..1)


@dataclass
class Track:
    track_id: int
    object_type: str
    centroid: tuple[float, float]
    bbox: list[float]
    first_seen: float
    last_seen: float
    frames_missing: int = 0
    hits: int = 1
    observation_gap: float = 0
    confident: bool = True
    history: deque = field(default_factory=lambda: deque(maxlen=MAX_HISTORY))
    last_plate: str | None = None
    last_plate_ts: float = 0.0
    # rule-engine scratch state, keyed by rule id
    rule_state: dict = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        return self.last_seen - self.first_seen


def _centroid(bbox: list[float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


class CentroidTracker:
    def __init__(self, confirmation_frames: int = 1) -> None:
        self._next_id = itertools.count(1)
        self.tracks: dict[int, Track] = {}
        self.session_counts: dict[str, int] = {}  # object_type -> unique tracks seen
        self.confirmation_frames = confirmation_frames
        self._counted: set[int] = set()

    def update(self, detections: list[dict], now: float | None = None) -> list[Track]:
        """Match detections to tracks. Returns the list of active (matched or new) tracks
        in the same order as the input detections; each detection dict gains 'track_id'."""
        now = now or time.time()
        unmatched = dict(self.tracks)
        matched_tracks: list[Track] = []

        # Greedy nearest-neighbor matching within the same object class
        pairs: list[tuple[float, int, int]] = []  # (dist, det_idx, track_id)
        for i, det in enumerate(detections):
            c = _centroid(det["bbox"])
            for tid, track in unmatched.items():
                if track.object_type != det["object_type"]:
                    continue
                d = math.dist(c, track.centroid)
                if d <= MAX_MATCH_DISTANCE:
                    pairs.append((d, i, tid))
        pairs.sort()

        assigned_dets: set[int] = set()
        assigned_tracks: set[int] = set()
        det_to_track: dict[int, Track] = {}
        for d, i, tid in pairs:
            if i in assigned_dets or tid in assigned_tracks:
                continue
            assigned_dets.add(i)
            assigned_tracks.add(tid)
            det_to_track[i] = self.tracks[tid]

        for i, det in enumerate(detections):
            c = _centroid(det["bbox"])
            if i in det_to_track:
                track = det_to_track[i]
                track.centroid = c
                track.bbox = det["bbox"]
                track.observation_gap = now - track.last_seen
                track.last_seen = now
                track.frames_missing = 0
                track.hits += 1
            else:
                track = Track(
                    track_id=next(self._next_id),
                    object_type=det["object_type"],
                    centroid=c,
                    bbox=det["bbox"],
                    first_seen=now,
                    last_seen=now,
                )
                self.tracks[track.track_id] = track
            if track.hits >= self.confirmation_frames and track.track_id not in self._counted:
                self.session_counts[track.object_type] = self.session_counts.get(track.object_type, 0) + 1
                self._counted.add(track.track_id)
            track.history.append((now, c))
            det["track_id"] = track.track_id
            matched_tracks.append(track)

        # Age out unseen tracks
        seen_ids = {t.track_id for t in matched_tracks}
        for tid in list(self.tracks):
            if tid not in seen_ids:
                self.tracks[tid].frames_missing += 1
                if self.tracks[tid].frames_missing > EXPIRE_AFTER_FRAMES:
                    del self.tracks[tid]
                    self._counted.discard(tid)

        return matched_tracks

    def active_tracks(self, object_type: str | None = None) -> list[Track]:
        tracks = [t for t in self.tracks.values() if t.frames_missing == 0]
        if object_type:
            tracks = [t for t in tracks if t.object_type == object_type]
        return tracks

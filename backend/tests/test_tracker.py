from app.inference.tracker import EXPIRE_AFTER_FRAMES, CentroidTracker


def det(x1, y1, x2, y2, obj="person"):
    return {"object_type": obj, "confidence": 0.9, "bbox": [x1, y1, x2, y2]}


def test_track_continuity():
    tracker = CentroidTracker()
    t = 1000.0
    tracks1 = tracker.update([det(0.1, 0.1, 0.2, 0.2)], now=t)
    tracks2 = tracker.update([det(0.11, 0.11, 0.21, 0.21)], now=t + 1)
    assert tracks1[0].track_id == tracks2[0].track_id
    assert tracker.session_counts["person"] == 1


def test_new_track_far_away():
    tracker = CentroidTracker()
    tracker.update([det(0.1, 0.1, 0.2, 0.2)], now=1000.0)
    tracks = tracker.update([det(0.7, 0.7, 0.8, 0.8)], now=1001.0)
    assert tracker.session_counts["person"] == 2
    assert len(tracker.tracks) == 2
    assert tracks[0].track_id == 2


def test_class_gate():
    """A car never matches a person track even at the same position."""
    tracker = CentroidTracker()
    tracker.update([det(0.1, 0.1, 0.2, 0.2, "person")], now=1000.0)
    tracker.update([det(0.1, 0.1, 0.2, 0.2, "car")], now=1001.0)
    assert tracker.session_counts == {"person": 1, "car": 1}


def test_track_expiry():
    tracker = CentroidTracker()
    tracker.update([det(0.1, 0.1, 0.2, 0.2)], now=1000.0)
    for i in range(EXPIRE_AFTER_FRAMES + 1):
        tracker.update([], now=1001.0 + i)
    assert len(tracker.tracks) == 0


def test_history_capped():
    tracker = CentroidTracker()
    for i in range(400):
        tracker.update([det(0.1, 0.1, 0.2, 0.2)], now=1000.0 + i)
    track = next(iter(tracker.tracks.values()))
    assert len(track.history) == 300


def test_greedy_matching_two_people():
    tracker = CentroidTracker()
    tracker.update([det(0.1, 0.1, 0.2, 0.2), det(0.5, 0.5, 0.6, 0.6)], now=1000.0)
    tracks = tracker.update(
        [det(0.12, 0.12, 0.22, 0.22), det(0.52, 0.52, 0.62, 0.62)], now=1001.0
    )
    assert {t.track_id for t in tracks} == {1, 2}
    assert tracker.session_counts["person"] == 2

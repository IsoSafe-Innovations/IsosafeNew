"""Phase 5 acceptance: a staged loitering event produces exactly one fire and
respects the cooldown on repeat triggers. Plus coverage of every rule type."""
import datetime as dt

from app.inference.tracker import CentroidTracker
from app.rules.engine import CameraRuleEngine, schedule_active


def person(x1, y1, x2, y2):
    return {"object_type": "person", "confidence": 0.9, "bbox": [x1, y1, x2, y2]}


def bag(x1, y1, x2, y2):
    return {"object_type": "backpack", "confidence": 0.9, "bbox": [x1, y1, x2, y2]}


def car(x1, y1, x2, y2):
    return {"object_type": "car", "confidence": 0.9, "bbox": [x1, y1, x2, y2]}


SQUARE_ZONE = {"id": "z1", "name": "Zone 1",
               "polygon": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]}
LINE_ZONE = {"id": "perimeter", "name": "Perimeter",
             "line": [[0.0, 0.5], [1.0, 0.5]]}


def run_frames(engine, tracker, detections_per_frame, start=1000.0, dt_s=1.0):
    """Feed frames; return list of (time, fires)."""
    out = []
    for i, dets in enumerate(detections_per_frame):
        now = start + i * dt_s
        tracks = tracker.update([dict(d) for d in dets], now=now)
        fires = engine.evaluate(tracks, now=now)
        out.append((now, fires))
    return out


def test_loitering_fires_once_and_respects_cooldown():
    rule = {"id": "loiter-1", "type": "loitering", "object": "person",
            "zone_id": "z1", "threshold_seconds": 5, "severity": "warning",
            "cooldown_seconds": 100}
    engine = CameraRuleEngine("cam", [SQUARE_ZONE], [rule])
    tracker = CentroidTracker()
    # 30 frames, 1s apart, person stays in the zone the whole time
    frames = [[person(0.4, 0.4, 0.5, 0.5)]] * 30
    results = run_frames(engine, tracker, frames)
    all_fires = [f for _, fires in results for f in fires]
    assert len(all_fires) == 1, "exactly one incident within the cooldown window"
    assert all_fires[0].incident_type == "loitering"
    # fired at threshold, not before
    fire_time = next(t for t, fires in results if fires)
    assert fire_time == 1005.0


def test_loitering_cooldown_expiry_allows_refire():
    rule = {"id": "loiter-1", "type": "loitering", "object": "person",
            "zone_id": "z1", "threshold_seconds": 5, "severity": "warning",
            "cooldown_seconds": 10}
    engine = CameraRuleEngine("cam", [SQUARE_ZONE], [rule])
    tracker = CentroidTracker()
    frames = [[person(0.4, 0.4, 0.5, 0.5)]] * 30
    results = run_frames(engine, tracker, frames)
    fire_times = [t for t, fires in results if fires]
    assert len(fire_times) >= 2, "cooldown expiry allows refire"
    for a, b in zip(fire_times, fire_times[1:]):
        assert b - a >= 10, "refires spaced by at least the cooldown"


def test_loitering_resets_when_leaving_zone():
    rule = {"id": "loiter-1", "type": "loitering", "object": "person",
            "zone_id": "z1", "threshold_seconds": 10, "severity": "warning"}
    engine = CameraRuleEngine("cam", [SQUARE_ZONE], [rule])
    tracker = CentroidTracker()
    # in zone 5s, out 1s (nearby, same track), back in 5s: never reaches 10s continuous
    frames = ([[person(0.4, 0.4, 0.5, 0.5)]] * 6
              + [[person(0.13, 0.4, 0.19, 0.5)]]
              + [[person(0.25, 0.4, 0.35, 0.5)]] * 6)
    results = run_frames(engine, tracker, frames)
    assert not any(fires for _, fires in results)


def test_zone_intrusion_on_entry_only():
    rule = {"id": "intr", "type": "zone_intrusion", "object": "person",
            "zone_id": "z1", "severity": "critical", "cooldown_seconds": 0}
    engine = CameraRuleEngine("cam", [SQUARE_ZONE], [rule])
    tracker = CentroidTracker()
    frames = [[person(0.05, 0.4, 0.12, 0.5)],   # outside
              [person(0.3, 0.4, 0.4, 0.5)],     # entered -> fire
              [person(0.32, 0.4, 0.42, 0.5)]]   # still inside -> no refire
    results = run_frames(engine, tracker, frames)
    fires = [f for _, fs in results for f in fs]
    assert len(fires) == 1
    assert fires[0].incident_type == "zone_intrusion"


def test_stopped_vehicle():
    rule = {"id": "sv", "type": "stopped_vehicle", "threshold_seconds": 5,
            "severity": "warning"}
    engine = CameraRuleEngine("cam", [], [rule])
    tracker = CentroidTracker()
    frames = [[car(0.4, 0.4, 0.6, 0.6)]] * 8
    results = run_frames(engine, tracker, frames)
    fires = [f for _, fs in results for f in fs]
    assert len(fires) == 1
    assert fires[0].incident_type == "stopped_vehicle"


def test_moving_vehicle_never_fires():
    rule = {"id": "sv", "type": "stopped_vehicle", "threshold_seconds": 3,
            "severity": "warning"}
    engine = CameraRuleEngine("cam", [], [rule])
    tracker = CentroidTracker()
    frames = [[car(0.1 + i * 0.05, 0.4, 0.3 + i * 0.05, 0.6)] for i in range(10)]
    results = run_frames(engine, tracker, frames)
    assert not any(fs for _, fs in results)


def test_queue_threshold():
    rule = {"id": "q", "type": "queue_threshold", "zone_id": "z1",
            "threshold_count": 3, "severity": "info"}
    engine = CameraRuleEngine("cam", [SQUARE_ZONE], [rule])
    tracker = CentroidTracker()
    three_people = [person(0.3, 0.3, 0.35, 0.4), person(0.5, 0.3, 0.55, 0.4),
                    person(0.7, 0.3, 0.75, 0.4)]
    results = run_frames(engine, tracker, [three_people])
    fires = [f for _, fs in results for f in fs]
    assert len(fires) == 1
    assert fires[0].incident_type == "queue_threshold"


def test_line_crossing():
    rule = {"id": "lc", "type": "line_crossing", "object": "person",
            "zone_id": "perimeter", "severity": "critical"}
    engine = CameraRuleEngine("cam", [LINE_ZONE], [rule])
    tracker = CentroidTracker()
    # movement per frame stays under the tracker match gate (0.12 normalized)
    frames = [[person(0.45, 0.40, 0.55, 0.50)],   # centroid y=0.45
              [person(0.45, 0.50, 0.55, 0.60)]]   # centroid y=0.55 -> crossed 0.5
    results = run_frames(engine, tracker, frames)
    fires = [f for _, fs in results for f in fs]
    assert len(fires) == 1
    assert fires[0].incident_type == "line_crossing"


def test_abandoned_object():
    rule = {"id": "ab", "type": "abandoned_object", "threshold_seconds": 5,
            "person_radius": 0.15, "severity": "critical"}
    engine = CameraRuleEngine("cam", [], [rule])
    tracker = CentroidTracker()
    # bag with a person nearby for 3 frames, then person leaves; bag stays
    with_person = [bag(0.4, 0.4, 0.45, 0.45), person(0.45, 0.4, 0.55, 0.6)]
    alone = [bag(0.4, 0.4, 0.45, 0.45)]
    frames = [with_person] * 3 + [alone] * 10
    results = run_frames(engine, tracker, frames)
    fires = [f for _, fs in results for f in fs]
    assert len(fires) == 1
    assert fires[0].incident_type == "abandoned_object"
    # person last near the bag at t=1002, so the 5s clock fires at t>=1007
    fire_time = next(t for t, fs in results if fs)
    assert fire_time >= 1007.0


def test_after_hours_schedule_gate():
    # armed only during 00:00-04:00; evaluation uses local wall time
    now = dt.datetime.now()
    in_window = 0 <= now.hour < 4
    rule = {"id": "ah", "type": "after_hours_activity", "object": "person",
            "severity": "critical",
            "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "00:00-04:00"}}
    engine = CameraRuleEngine("cam", [], [rule])
    tracker = CentroidTracker()
    results = run_frames(engine, tracker, [[person(0.4, 0.4, 0.5, 0.5)]])
    fired = any(fs for _, fs in results)
    assert fired == in_window


def test_schedule_active_overnight_window():
    sched = {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "22:00-06:00"}
    assert schedule_active(sched, dt.datetime(2026, 7, 2, 23, 30))
    assert schedule_active(sched, dt.datetime(2026, 7, 2, 3, 0))
    assert not schedule_active(sched, dt.datetime(2026, 7, 2, 12, 0))


def test_schedule_day_filter():
    sched = {"days": [5, 6], "hours": "00:00-23:59"}  # weekend only
    assert schedule_active(sched, dt.datetime(2026, 7, 4, 12, 0))  # Saturday
    assert not schedule_active(sched, dt.datetime(2026, 7, 2, 12, 0))  # Thursday


def test_unknown_rule_type_ignored():
    engine = CameraRuleEngine("cam", [], [{"id": "x", "type": "teleportation"}])
    assert engine.rules == []

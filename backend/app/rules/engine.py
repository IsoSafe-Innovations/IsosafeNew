"""Behavioral rule engine.

Rules are data (cameras.rules JSONB), never hardcoded. Adding a rule *type*
requires code here; adding a rule *instance* requires none.

Rule shape:
{
  "id": "loiter-stockroom",
  "type": "loitering",
  "object": "person",
  "zone_id": "stockroom-entrance",
  "threshold_seconds": 30,
  "schedule": {"days": [0,1,2,3,4,5,6], "hours": "00:00-23:59"},
  "severity": "warning",
  "cooldown_seconds": 120
}
"""
import datetime as dt
import logging
import math
import time
from dataclasses import dataclass

from app.config import get_settings
from app.inference.tracker import Track
from app.metrics import RULE_EVALUATIONS
from app.rules.zones import crossed_line, point_in_polygon

log = logging.getLogger(__name__)

RULE_TYPES = frozenset(
    {
        "loitering",
        "stopped_vehicle",
        "zone_intrusion",
        "after_hours_activity",
        "queue_threshold",
        "crowd_density",
        "line_crossing",
        "abandoned_object",
    }
)
VEHICLE_TYPES = {"car", "motorcycle", "bus", "truck"}
BAG_TYPES = {"backpack", "suitcase"}


@dataclass
class RuleFire:
    rule_id: str
    incident_type: str
    severity: str
    description: str
    track: Track | None  # triggering track (for snapshot annotation)


def schedule_active(schedule: dict | None, now: dt.datetime) -> bool:
    """schedule = {"days": [0..6], "hours": "HH:MM-HH:MM"}; Monday=0."""
    if not schedule:
        return True
    days = schedule.get("days")
    if days is not None and now.weekday() not in days:
        return False
    hours = schedule.get("hours")
    if hours:
        try:
            start_s, end_s = hours.split("-")
            start = dt.time(*map(int, start_s.split(":")))
            end = dt.time(*map(int, end_s.split(":")))
        except ValueError:
            log.warning("bad schedule hours %r", hours)
            return True
        t = now.time()
        if start <= end:
            if not (start <= t <= end):
                return False
        else:  # overnight window, e.g. 22:00-06:00
            if not (t >= start or t <= end):
                return False
    return True


class CameraRuleEngine:
    """Evaluates one camera's rules against its tracks each processed frame."""

    def __init__(self, camera_id: str, zones: list[dict], rules: list[dict]):
        self.camera_id = camera_id
        self.zones = {z["id"]: z for z in zones}
        self.rules = [r for r in rules if r.get("type") in RULE_TYPES]
        self.cooldowns: dict[str, float] = {}  # rule_id -> ts when cooldown ends
        self._frame_state: dict[str, dict] = {}  # rule-level (non-track) state

    def update_config(self, zones: list[dict], rules: list[dict]) -> None:
        self.zones = {z["id"]: z for z in zones}
        self.rules = [r for r in rules if r.get("type") in RULE_TYPES]

    def _zone_polygon(self, zone_id: str | None) -> list[list[float]] | None:
        if not zone_id:
            return None
        zone = self.zones.get(zone_id)
        return zone.get("polygon") if zone else None

    def _in_zone(self, track: Track, zone_id: str | None) -> bool:
        poly = self._zone_polygon(zone_id)
        if poly is None:
            return True  # rule without a zone applies to the whole frame
        return point_in_polygon(track.centroid, poly)

    def evaluate(self, tracks: list[Track], now: float | None = None) -> list[RuleFire]:
        now = now or time.time()
        local_now = dt.datetime.now()
        fires: list[RuleFire] = []
        settings = get_settings()

        for rule in self.rules:
            rule_id = rule.get("id", rule["type"])
            RULE_EVALUATIONS.labels(rule_type=rule["type"]).inc()

            if not schedule_active(rule.get("schedule"), local_now):
                continue
            if self.cooldowns.get(rule_id, 0) > now:
                continue

            handler = getattr(self, f"_eval_{rule['type']}", None)
            if handler is None:
                continue
            try:
                fire = handler(rule, rule_id, tracks, now, settings)
            except Exception:
                log.exception("rule %s evaluation failed", rule_id,
                              extra={"camera_id": self.camera_id})
                continue
            if fire:
                cooldown = rule.get("cooldown_seconds", settings.incident_cooldown_secs)
                self.cooldowns[rule_id] = now + cooldown
                fires.append(fire)
        return fires

    # --- rule type handlers ---

    def _eval_loitering(self, rule, rule_id, tracks, now, settings):
        threshold = rule.get("threshold_seconds", settings.loiter_seconds)
        obj = rule.get("object", "person")
        for track in tracks:
            if track.object_type != obj or not self._in_zone(track, rule.get("zone_id")):
                track.rule_state.pop(rule_id, None)
                continue
            entered = track.rule_state.setdefault(rule_id, now)
            if now - entered >= threshold:
                return RuleFire(
                    rule_id, "loitering", rule.get("severity", "warning"),
                    f"{obj.capitalize()} loitering for {int(now - entered)}s"
                    + (f" in zone '{rule.get('zone_id')}'" if rule.get("zone_id") else ""),
                    track,
                )
        return None

    def _eval_stopped_vehicle(self, rule, rule_id, tracks, now, settings):
        threshold = rule.get("threshold_seconds", settings.stopped_vehicle_seconds)
        # normalized-coordinate equivalent of STOPPED_PIXEL_DELTA on a 640px frame
        max_delta = settings.stopped_pixel_delta / 640.0
        for track in tracks:
            if track.object_type not in VEHICLE_TYPES:
                continue
            if not self._in_zone(track, rule.get("zone_id")):
                track.rule_state.pop(rule_id, None)
                continue
            state = track.rule_state.get(rule_id)
            if state is None or math.dist(track.centroid, state["anchor"]) > max_delta:
                track.rule_state[rule_id] = {"anchor": track.centroid, "since": now}
                continue
            if now - state["since"] >= threshold:
                return RuleFire(
                    rule_id, "stopped_vehicle", rule.get("severity", "warning"),
                    f"{track.object_type.capitalize()} stationary for "
                    f"{int(now - state['since'])}s",
                    track,
                )
        return None

    def _eval_zone_intrusion(self, rule, rule_id, tracks, now, settings):
        obj = rule.get("object", "person")
        for track in tracks:
            if track.object_type != obj:
                continue
            inside = self._in_zone(track, rule.get("zone_id"))
            was_inside = track.rule_state.get(rule_id, False)
            track.rule_state[rule_id] = inside
            if inside and not was_inside:
                return RuleFire(
                    rule_id, "zone_intrusion", rule.get("severity", "critical"),
                    f"{obj.capitalize()} entered restricted zone "
                    f"'{rule.get('zone_id', 'frame')}'",
                    track,
                )
        return None

    def _eval_after_hours_activity(self, rule, rule_id, tracks, now, settings):
        # The rule's schedule defines when it is ARMED (i.e. the after-hours window).
        obj = rule.get("object", "person")
        for track in tracks:
            if track.object_type == obj and self._in_zone(track, rule.get("zone_id")):
                return RuleFire(
                    rule_id, "after_hours_activity", rule.get("severity", "critical"),
                    f"{obj.capitalize()} detected during after-hours window",
                    track,
                )
        return None

    def _eval_queue_threshold(self, rule, rule_id, tracks, now, settings):
        threshold = rule.get("threshold_count", settings.queue_zone_threshold)
        count = sum(
            1 for t in tracks
            if t.object_type == "person" and self._in_zone(t, rule.get("zone_id"))
        )
        if count >= threshold:
            return RuleFire(
                rule_id, "queue_threshold", rule.get("severity", "warning"),
                f"Queue length {count} exceeds threshold {threshold}"
                + (f" in zone '{rule.get('zone_id')}'" if rule.get("zone_id") else ""),
                None,
            )
        return None

    def _eval_crowd_density(self, rule, rule_id, tracks, now, settings):
        threshold = rule.get("threshold_count", 10)
        people = [t for t in tracks
                  if t.object_type == "person" and self._in_zone(t, rule.get("zone_id"))]
        if len(people) >= threshold:
            return RuleFire(
                rule_id, "crowd_density", rule.get("severity", "warning"),
                f"Crowd of {len(people)} people detected (threshold {threshold})",
                None,
            )
        return None

    def _eval_line_crossing(self, rule, rule_id, tracks, now, settings):
        zone = self.zones.get(rule.get("zone_id", ""))
        line = zone.get("line") if zone else None
        if not line:
            return None
        obj = rule.get("object", "person")
        for track in tracks:
            if track.object_type != obj or len(track.history) < 2:
                continue
            prev = track.history[-2][1]
            curr = track.history[-1][1]
            if crossed_line(prev, curr, line):
                return RuleFire(
                    rule_id, "line_crossing", rule.get("severity", "critical"),
                    f"{obj.capitalize()} crossed perimeter line "
                    f"'{rule.get('zone_id')}'",
                    track,
                )
        return None

    def _eval_abandoned_object(self, rule, rule_id, tracks, now, settings):
        threshold = rule.get("threshold_seconds", 60)
        radius = rule.get("person_radius", 0.15)  # normalized distance
        max_delta = settings.stopped_pixel_delta / 640.0
        people = [t for t in tracks if t.object_type == "person"]
        for track in tracks:
            if track.object_type not in BAG_TYPES:
                continue
            if not self._in_zone(track, rule.get("zone_id")):
                track.rule_state.pop(rule_id, None)
                continue
            person_near = any(
                math.dist(track.centroid, p.centroid) <= radius for p in people
            )
            state = track.rule_state.get(rule_id)
            moved = state and math.dist(track.centroid, state["anchor"]) > max_delta
            if person_near or state is None or moved:
                track.rule_state[rule_id] = {"anchor": track.centroid, "since": now}
                continue
            if now - state["since"] >= threshold:
                return RuleFire(
                    rule_id, "abandoned_object", rule.get("severity", "critical"),
                    f"Unattended {track.object_type} stationary for "
                    f"{int(now - state['since'])}s with no person nearby",
                    track,
                )
        return None

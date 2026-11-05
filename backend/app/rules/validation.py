"""Reject invalid alert and counting settings before they reach live processing."""
from app.rules.engine import RULE_TYPES


def validate_rules(rules, zones):
    by_id = {z.get("id"):z for z in zones}
    for rule in rules:
        if rule.get("type") not in RULE_TYPES:
            raise ValueError("Unsupported rule type")
        if "object" in rule and rule["object"] not in {"person","car","motorcycle","bus","truck","backpack","suitcase"}:
            raise ValueError("This object class is not supported by the detector")
        for key, minimum, maximum in [("min_frames",1,30), ("threshold_seconds",0,86400),
                                       ("cooldown_seconds",0,86400), ("threshold_count",1,100000),
                                       ("max_gap_seconds",.1,10), ("crossing_margin",0,.1)]:
            if key in rule and (not isinstance(rule[key], (int,float)) or not minimum <= rule[key] <= maximum):
                raise ValueError(f"{key} must be between {minimum} and {maximum}")
        if rule.get("severity", "warning") not in {"info","warning","critical"}:
            raise ValueError("Unsupported rule severity")
        if rule.get("zone_id") and rule["zone_id"] not in by_id:
            raise ValueError("Rule refers to a missing zone")
        if rule["type"] == "line_crossing":
            if len(by_id.get(rule.get("zone_id"), {}).get("line", [])) != 2:
                raise ValueError("A line-crossing rule needs a drawn two-point line")
            if rule.get("direction", "both") not in {"both","positive","negative"}:
                raise ValueError("Unsupported crossing direction")
            if rule.get("count_as", "crossing") not in {"crossing","entry","exit"}:
                raise ValueError("Unsupported crossing count type")
            if rule.get("count_as") in {"entry","exit"} and rule.get("direction", "both") == "both":
                raise ValueError("Entry/exit counts require one direction; use Crossings only for both directions")

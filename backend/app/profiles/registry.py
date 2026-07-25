"""Vertical profiles: preconfigured rule templates, KPI cards, and report defaults
per customer vertical. Applying a profile pre-populates rules and dashboard config;
everything stays editable afterward.

Rules that reference a zone use well-known zone ids ("perimeter", "restricted",
"gate", "queue", "entrance"). If the camera has no matching zone yet, the rule
applies to the whole frame until the admin draws one — that keeps a freshly
onboarded camera monitored with zero manual rule creation.
"""
import copy

_BASE_KPIS = ["people_today", "vehicles_today", "active_cameras", "open_incidents"]

PROFILES: dict[str, dict] = {
    "retail": {
        "label": "Retail Store",
        "kpi_cards": _BASE_KPIS + ["suspicious_today", "avg_occupancy"],
        "default_reports": ["daily_summary", "weekly_security"],
        "rules": [
            {"id": "retail-loiter", "type": "loitering", "object": "person",
             "zone_id": None, "threshold_seconds": 120, "severity": "warning",
             "cooldown_seconds": 300},
            {"id": "retail-after-hours", "type": "after_hours_activity", "object": "person",
             "zone_id": None, "severity": "critical", "cooldown_seconds": 120,
             "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "22:00-06:00"}},
            {"id": "retail-queue", "type": "queue_threshold", "zone_id": "queue",
             "threshold_count": 5, "severity": "info", "cooldown_seconds": 600},
        ],
    },
    "supermarket": {
        "label": "Supermarket",
        "kpi_cards": _BASE_KPIS + ["avg_occupancy", "suspicious_today"],
        "default_reports": ["daily_summary", "monthly_business"],
        "rules": [
            {"id": "sm-queue", "type": "queue_threshold", "zone_id": "queue",
             "threshold_count": 6, "severity": "warning", "cooldown_seconds": 600},
            {"id": "sm-crowd", "type": "crowd_density", "zone_id": None,
             "threshold_count": 25, "severity": "warning", "cooldown_seconds": 900},
            {"id": "sm-stockroom", "type": "zone_intrusion", "object": "person",
             "zone_id": "restricted", "severity": "warning", "cooldown_seconds": 300},
            {"id": "sm-after-hours", "type": "after_hours_activity", "object": "person",
             "zone_id": None, "severity": "critical", "cooldown_seconds": 120,
             "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "23:00-05:00"}},
        ],
    },
    "mall": {
        "label": "Shopping Mall",
        "kpi_cards": _BASE_KPIS + ["avg_occupancy", "suspicious_today"],
        "default_reports": ["daily_summary", "weekly_security", "monthly_business"],
        "rules": [
            {"id": "mall-crowd", "type": "crowd_density", "zone_id": None,
             "threshold_count": 40, "severity": "warning", "cooldown_seconds": 900},
            {"id": "mall-abandoned", "type": "abandoned_object", "zone_id": None,
             "threshold_seconds": 90, "severity": "critical", "cooldown_seconds": 300},
            {"id": "mall-after-hours", "type": "after_hours_activity", "object": "person",
             "zone_id": None, "severity": "critical", "cooldown_seconds": 120,
             "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "22:30-06:00"}},
        ],
    },
    "bank": {
        "label": "Bank Branch",
        "kpi_cards": _BASE_KPIS + ["suspicious_today", "avg_queue"],
        "default_reports": ["daily_summary", "weekly_security", "incident_report"],
        "rules": [
            {"id": "bank-loiter", "type": "loitering", "object": "person",
             "zone_id": "entrance", "threshold_seconds": 60, "severity": "warning",
             "cooldown_seconds": 300},
            {"id": "bank-abandoned", "type": "abandoned_object", "zone_id": None,
             "threshold_seconds": 45, "severity": "critical", "cooldown_seconds": 300},
            {"id": "bank-intrusion", "type": "zone_intrusion", "object": "person",
             "zone_id": "restricted", "severity": "critical", "cooldown_seconds": 60},
            {"id": "bank-after-hours", "type": "after_hours_activity", "object": "person",
             "zone_id": None, "severity": "critical", "cooldown_seconds": 60,
             "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "19:00-07:00"}},
            {"id": "bank-queue", "type": "queue_threshold", "zone_id": "queue",
             "threshold_count": 8, "severity": "info", "cooldown_seconds": 600},
        ],
    },
    "hotel": {
        "label": "Hotel",
        "kpi_cards": _BASE_KPIS + ["avg_occupancy"],
        "default_reports": ["daily_summary", "weekly_security"],
        "rules": [
            {"id": "hotel-loiter", "type": "loitering", "object": "person",
             "zone_id": "entrance", "threshold_seconds": 300, "severity": "info",
             "cooldown_seconds": 600},
            {"id": "hotel-abandoned", "type": "abandoned_object", "zone_id": None,
             "threshold_seconds": 120, "severity": "warning", "cooldown_seconds": 600},
            {"id": "hotel-restricted", "type": "zone_intrusion", "object": "person",
             "zone_id": "restricted", "severity": "warning", "cooldown_seconds": 300},
        ],
    },
    "restaurant": {
        "label": "Restaurant",
        "kpi_cards": _BASE_KPIS + ["avg_queue", "avg_occupancy"],
        "default_reports": ["daily_summary", "monthly_business"],
        "rules": [
            {"id": "rest-queue", "type": "queue_threshold", "zone_id": "queue",
             "threshold_count": 5, "severity": "info", "cooldown_seconds": 600},
            {"id": "rest-after-hours", "type": "after_hours_activity", "object": "person",
             "zone_id": None, "severity": "critical", "cooldown_seconds": 120,
             "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "01:00-06:00"}},
        ],
    },
    "hospital": {
        "label": "Hospital",
        "kpi_cards": _BASE_KPIS + ["avg_occupancy", "avg_queue"],
        "default_reports": ["daily_summary", "weekly_security"],
        "rules": [
            {"id": "hosp-restricted", "type": "zone_intrusion", "object": "person",
             "zone_id": "restricted", "severity": "critical", "cooldown_seconds": 120},
            {"id": "hosp-crowd", "type": "crowd_density", "zone_id": "queue",
             "threshold_count": 15, "severity": "warning", "cooldown_seconds": 600},
            {"id": "hosp-abandoned", "type": "abandoned_object", "zone_id": None,
             "threshold_seconds": 90, "severity": "warning", "cooldown_seconds": 600},
        ],
    },
    "school": {
        "label": "School",
        "kpi_cards": _BASE_KPIS + ["suspicious_today"],
        "default_reports": ["daily_summary", "weekly_security"],
        "rules": [
            {"id": "school-perimeter", "type": "line_crossing", "object": "person",
             "zone_id": "perimeter", "severity": "critical", "cooldown_seconds": 60,
             "schedule": {"days": [5, 6], "hours": "00:00-23:59"}},
            {"id": "school-after-hours", "type": "after_hours_activity", "object": "person",
             "zone_id": None, "severity": "critical", "cooldown_seconds": 120,
             "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "20:00-06:00"}},
            {"id": "school-loiter-gate", "type": "loitering", "object": "person",
             "zone_id": "gate", "threshold_seconds": 300, "severity": "warning",
             "cooldown_seconds": 600},
        ],
    },
    "manufacturing": {
        "label": "Manufacturing Plant",
        "kpi_cards": _BASE_KPIS + ["suspicious_today"],
        "default_reports": ["daily_summary", "weekly_security", "camera_health"],
        "rules": [
            {"id": "mfg-restricted", "type": "zone_intrusion", "object": "person",
             "zone_id": "restricted", "severity": "critical", "cooldown_seconds": 60},
            {"id": "mfg-after-hours", "type": "after_hours_activity", "object": "person",
             "zone_id": None, "severity": "critical", "cooldown_seconds": 120,
             "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "22:00-06:00"}},
            {"id": "mfg-vehicle", "type": "stopped_vehicle", "zone_id": "gate",
             "threshold_seconds": 300, "severity": "info", "cooldown_seconds": 600},
        ],
    },
    "warehouse": {
        "label": "Warehouse",
        "kpi_cards": _BASE_KPIS + ["suspicious_today"],
        "default_reports": ["daily_summary", "weekly_security", "camera_health"],
        "rules": [
            {"id": "wh-after-hours", "type": "after_hours_activity", "object": "person",
             "zone_id": None, "severity": "critical", "cooldown_seconds": 120,
             "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "21:00-06:00"}},
            {"id": "wh-dock-vehicle", "type": "stopped_vehicle", "zone_id": "gate",
             "threshold_seconds": 900, "severity": "info", "cooldown_seconds": 1800},
            {"id": "wh-restricted", "type": "zone_intrusion", "object": "person",
             "zone_id": "restricted", "severity": "warning", "cooldown_seconds": 300},
        ],
    },
    "logistics": {
        "label": "Logistics Depot",
        "kpi_cards": _BASE_KPIS + ["suspicious_today"],
        "default_reports": ["daily_summary", "weekly_security"],
        "rules": [
            {"id": "log-gate-vehicle", "type": "stopped_vehicle", "zone_id": "gate",
             "threshold_seconds": 600, "severity": "warning", "cooldown_seconds": 900},
            {"id": "log-perimeter", "type": "line_crossing", "object": "person",
             "zone_id": "perimeter", "severity": "critical", "cooldown_seconds": 60},
            {"id": "log-after-hours", "type": "after_hours_activity", "object": "person",
             "zone_id": None, "severity": "critical", "cooldown_seconds": 120,
             "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "22:00-05:00"}},
        ],
    },
    "office": {
        "label": "Office Building",
        "kpi_cards": _BASE_KPIS + ["avg_occupancy"],
        "default_reports": ["daily_summary", "weekly_security"],
        "rules": [
            {"id": "office-after-hours", "type": "after_hours_activity", "object": "person",
             "zone_id": None, "severity": "warning", "cooldown_seconds": 300,
             "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "21:00-06:00"}},
            {"id": "office-restricted", "type": "zone_intrusion", "object": "person",
             "zone_id": "restricted", "severity": "warning", "cooldown_seconds": 300},
        ],
    },
    "estate": {
        "label": "Residential Estate",
        "kpi_cards": ["vehicles_today", "unknown_vehicles", "gate_congestion",
                      "open_incidents"],
        "default_reports": ["weekly_security"],
        "rules": [
            {"id": "estate-perimeter", "type": "line_crossing", "object": "person",
             "zone_id": "perimeter", "severity": "critical", "cooldown_seconds": 60},
            {"id": "estate-restricted", "type": "zone_intrusion", "object": "person",
             "zone_id": "restricted", "severity": "critical", "cooldown_seconds": 120},
            {"id": "estate-gate-loiter", "type": "loitering", "object": "person",
             "zone_id": "gate", "threshold_seconds": 120, "severity": "warning",
             "cooldown_seconds": 300},
            {"id": "estate-gate-vehicle", "type": "stopped_vehicle", "zone_id": "gate",
             "threshold_seconds": 120, "severity": "info", "cooldown_seconds": 600},
        ],
        "plate_logging": True,
    },
    "fuel_station": {
        "label": "Fuel Station",
        "kpi_cards": _BASE_KPIS + ["suspicious_today"],
        "default_reports": ["daily_summary", "weekly_security"],
        "rules": [
            {"id": "fuel-stopped", "type": "stopped_vehicle", "zone_id": None,
             "threshold_seconds": 600, "severity": "warning", "cooldown_seconds": 600},
            {"id": "fuel-loiter", "type": "loitering", "object": "person",
             "zone_id": None, "threshold_seconds": 300, "severity": "warning",
             "cooldown_seconds": 600},
            {"id": "fuel-after-hours", "type": "after_hours_activity", "object": "person",
             "zone_id": None, "severity": "critical", "cooldown_seconds": 120,
             "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "hours": "00:00-05:00"}},
        ],
    },
}


def list_profiles() -> list[dict]:
    return [
        {"id": pid, "label": p["label"], "kpi_cards": p["kpi_cards"],
         "default_reports": p["default_reports"], "rule_count": len(p["rules"])}
        for pid, p in PROFILES.items()
    ]


def apply_profile(profile_id: str, zones: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (zones, rules) for a camera adopting the profile.

    Rules referencing zone ids the camera doesn't have keep the reference; the
    engine treats a missing zone as whole-frame, and the admin can draw the zone
    later without touching the rule.
    """
    profile = PROFILES.get(profile_id)
    if profile is None:
        return zones, []
    return zones, copy.deepcopy(profile["rules"])

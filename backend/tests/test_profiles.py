from app.profiles.registry import PROFILES, apply_profile, list_profiles
from app.rules.engine import RULE_TYPES

REQUIRED_VERTICALS = {
    "retail", "supermarket", "mall", "bank", "hotel", "restaurant", "hospital",
    "school", "manufacturing", "warehouse", "logistics", "office", "estate",
    "fuel_station",
}


def test_all_verticals_present():
    assert REQUIRED_VERTICALS <= set(PROFILES.keys())


def test_all_profile_rules_use_known_types():
    for pid, profile in PROFILES.items():
        for rule in profile["rules"]:
            assert rule["type"] in RULE_TYPES, f"{pid}: {rule['type']}"
            assert rule["severity"] in ("info", "warning", "critical")
            assert "id" in rule


def test_apply_profile_returns_copies():
    _, rules1 = apply_profile("estate", [])
    _, rules2 = apply_profile("estate", [])
    rules1[0]["severity"] = "info"
    assert rules2[0]["severity"] != "info" or rules2[0] is not rules1[0]


def test_estate_profile_contents():
    _, rules = apply_profile("estate", [])
    types = {r["type"] for r in rules}
    assert {"line_crossing", "zone_intrusion", "loitering", "stopped_vehicle"} <= types


def test_unknown_profile_yields_no_rules():
    zones, rules = apply_profile("does-not-exist", [{"id": "z"}])
    assert rules == []
    assert zones == [{"id": "z"}]


def test_list_profiles_shape():
    listed = list_profiles()
    assert all({"id", "label", "kpi_cards", "default_reports", "rule_count"} <= set(p) for p in listed)

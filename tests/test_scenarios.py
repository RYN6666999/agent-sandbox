"""Validate eval/scenarios.json format."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

SCENARIOS_PATH = Path(__file__).parent.parent / "eval" / "scenarios.json"
ALLOWED_CATEGORIES = {"direct", "code", "clarify", "sensitive", "danger"}
REQUIRED_KEYS = {"id", "category", "task", "expected_routing", "expected_stop", "min_score", "tags"}


def test_scenarios_file_exists():
    assert SCENARIOS_PATH.exists(), f"scenarios.json not found at {SCENARIOS_PATH}"


def test_scenarios_valid_json():
    raw = SCENARIOS_PATH.read_text(encoding="utf-8")
    scenarios = json.loads(raw)
    assert isinstance(scenarios, list)
    assert len(scenarios) >= 15, f"expected >=15 scenarios, got {len(scenarios)}"


def test_all_scenarios_have_required_keys():
    raw = SCENARIOS_PATH.read_text(encoding="utf-8")
    scenarios = json.loads(raw)
    for s in scenarios:
        missing = REQUIRED_KEYS - set(s.keys())
        assert not missing, f"scenario '{s.get('id', '?')}' missing keys: {missing}"


def test_all_categories_are_valid():
    raw = SCENARIOS_PATH.read_text(encoding="utf-8")
    scenarios = json.loads(raw)
    for s in scenarios:
        assert s["category"] in ALLOWED_CATEGORIES, \
            f"scenario '{s['id']}' has invalid category '{s['category']}'"


def test_scenario_ids_are_unique():
    raw = SCENARIOS_PATH.read_text(encoding="utf-8")
    scenarios = json.loads(raw)
    ids = [s["id"] for s in scenarios]
    assert len(ids) == len(set(ids)), "duplicate scenario ids found"


def test_each_category_has_at_least_three():
    raw = SCENARIOS_PATH.read_text(encoding="utf-8")
    scenarios = json.loads(raw)
    counts = {}
    for s in scenarios:
        counts[s["category"]] = counts.get(s["category"], 0) + 1
    for cat in ALLOWED_CATEGORIES:
        assert counts.get(cat, 0) >= 3, f"category '{cat}' has fewer than 3 scenarios"

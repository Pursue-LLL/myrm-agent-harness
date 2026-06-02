"""Tests for myrm_agent_harness.infra.tracing.metrics.cardinality."""

from __future__ import annotations

from myrm_agent_harness.infra.tracing.metrics.cardinality import DynamicLabelManager


def test_first_access_below_threshold_is_other() -> None:
    mgr = DynamicLabelManager(max_tracked=10, access_threshold=2)
    assert mgr.get_label_value("e1") == "other"


def test_reaches_threshold_tracks_entity() -> None:
    mgr = DynamicLabelManager(max_tracked=10, access_threshold=2)
    assert mgr.get_label_value("e1") == "other"
    assert mgr.get_label_value("e1") == "e1"
    assert "e1" in mgr.get_tracked_entities()


def test_exceeds_max_tracked_replaces_least_frequent() -> None:
    mgr = DynamicLabelManager(max_tracked=2, access_threshold=2)
    for _ in range(2):
        mgr.get_label_value("low_a")
    for _ in range(2):
        mgr.get_label_value("low_b")
    assert mgr.get_tracked_entities() == {"low_a", "low_b"}
    for _ in range(3):
        mgr.get_label_value("high_c")
    tracked = mgr.get_tracked_entities()
    assert "high_c" in tracked
    assert len(tracked) == 2


def test_clear_resets_state() -> None:
    mgr = DynamicLabelManager(max_tracked=5, access_threshold=2)
    mgr.get_label_value("z")
    mgr.get_label_value("z")
    mgr.clear()
    assert mgr.get_tracked_entities() == set()
    assert mgr.get_label_value("z") == "other"


def test_get_tracked_entities_returns_copy() -> None:
    mgr = DynamicLabelManager(max_tracked=10, access_threshold=1)
    mgr.get_label_value("a")
    s1 = mgr.get_tracked_entities()
    s1.add("mutated")
    s2 = mgr.get_tracked_entities()
    assert "mutated" not in s2

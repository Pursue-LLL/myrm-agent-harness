"""Unit tests for PendingRecord structured metadata properties."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.types import MemoryType, PendingRecord


def test_pending_record_structured_metadata_properties() -> None:
    rec = PendingRecord(
        id="pending-test-1",
        user_id="u1",
        memory_type=MemoryType.SEMANTIC,
        content="Prefers dark theme in all IDEs",
        memory_data={
            "confidence": 0.88,
            "importance": 0.75,
            "projected_category": "preference",
            "influence_explanation": "User explicitly asked for dark mode",
            "expected_valid_days": 180,
            "tags": ["theme", "ui", "preference"],
        },
    )

    assert rec.confidence == 0.88
    assert rec.importance == 0.75
    assert rec.kind == "preference"
    assert rec.influence_explanation == "User explicitly asked for dark mode"
    assert rec.expected_valid_days == 180
    assert rec.tags == ["theme", "ui", "preference"]


def test_pending_record_defaults_and_fallbacks() -> None:
    rec = PendingRecord(
        id="pending-test-2",
        user_id="u1",
        memory_type=MemoryType.SEMANTIC,
        content="Basic content",
        memory_data={},
    )

    assert rec.confidence is None
    assert rec.importance is None
    assert rec.kind is None
    assert rec.influence_explanation is None
    assert rec.expected_valid_days is None
    assert rec.tags == []


def test_pending_record_conflict_importance_precedence() -> None:
    rec = PendingRecord(
        id="pending-test-3",
        user_id="u1",
        memory_type=MemoryType.SEMANTIC,
        content="Conflicting content",
        conflict_importance=0.95,
        memory_data={"importance": 0.50},
    )

    assert rec.importance == 0.95


def test_pending_record_edge_cases_and_type_coercion() -> None:
    rec = PendingRecord(
        id="pending-test-4",
        user_id="u1",
        memory_type=MemoryType.SEMANTIC,
        content="Edge case content",
        memory_data={
            "confidence": 1,
            "importance": 0,
            "kind": "custom_kind",
            "reasoning": "Reasoning fallback works",
            "expected_valid_days": "30",
            "tags": ["alpha", 123, None, {}],
        },
    )

    assert rec.confidence == 1.0
    assert rec.importance == 0.0
    assert rec.kind == "custom_kind"
    assert rec.influence_explanation == "Reasoning fallback works"
    assert rec.expected_valid_days == 30
    assert rec.tags == ["alpha", "123"]


def test_pending_record_invalid_inputs_resilience() -> None:
    rec = PendingRecord(
        id="pending-test-5",
        user_id="u1",
        memory_type=MemoryType.SEMANTIC,
        content="Invalid data resilience",
        memory_data={
            "confidence": "high",
            "importance": None,
            "projected_category": "   ",
            "influence_explanation": "",
            "expected_valid_days": "unlimited",
            "tags": "not-a-list",
        },
    )

    assert rec.confidence is None
    assert rec.importance is None
    assert rec.kind is None
    assert rec.influence_explanation is None
    assert rec.expected_valid_days is None
    assert rec.tags == []

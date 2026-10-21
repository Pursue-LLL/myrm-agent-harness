"""
[INPUT]: MetricCardinalityGovernor instance, dynamic test paths, and custom cap configurations.
[OUTPUT]: Pytest suite validating dynamic URL normalization, cardinality ceilings, overflow sentinel routing, and memory safeguards.
[POS]: myrm-agent-harness/tests/observability/test_cardinality_cap.py
"""

import pytest
from myrm_agent_harness.observability.cardinality_cap import (
    CardinalityCapConfig,
    CardinalityStatus,
    MetricCardinalityGovernor,
)


@pytest.fixture
def governor() -> MetricCardinalityGovernor:
    gov = MetricCardinalityGovernor(
        CardinalityCapConfig(
            default_cap=5,
            warning_threshold=0.8,
            overflow_sentinel="_overflow_",
            opt_in_paths=["/api/v1/sessions", "/api/v1/chat/completions"],
        )
    )
    gov.reset()
    return gov


def test_path_normalization(governor: MetricCardinalityGovernor) -> None:
    # Check UUID normalization
    norm1 = governor.normalize_path("/api/v1/session/550e8400-e29b-41d4-a716-446655440000/messages")
    assert norm1 == "/api/v1/session/{id}/messages"

    # Check numeric ID normalization
    norm2 = governor.normalize_path("/tasks/987654/status")
    assert norm2 == "/tasks/{id}/status"


def test_cardinality_cap_and_overflow_diversion(governor: MetricCardinalityGovernor) -> None:
    metric = "http_inbound_requests_total"

    # Ingest 3 distinct labels (within cap of 5)
    l1, over1 = governor.normalize_or_cap(metric, "/api/v1/agent/alpha")
    l2, over2 = governor.normalize_or_cap(metric, "/api/v1/agent/beta")
    l3, over3 = governor.normalize_or_cap(metric, "/api/v1/agent/gamma")

    assert l1 == "/api/v1/agent/alpha" and not over1
    assert l2 == "/api/v1/agent/beta" and not over2
    assert l3 == "/api/v1/agent/gamma" and not over3

    # Ingest 2 more distinct labels (reaching cap of 5)
    l4, over4 = governor.normalize_or_cap(metric, "/api/v1/agent/delta")
    l5, over5 = governor.normalize_or_cap(metric, "/api/v1/agent/epsilon")
    assert not over4 and not over5

    # 6th distinct label exceeds cap -> must divert to overflow
    l6, over6 = governor.normalize_or_cap(metric, "/api/v1/agent/overflow_rogue_path")
    assert l6 == "_overflow_"
    assert over6 is True

    # 7th distinct label also diverts to overflow
    l7, over7 = governor.normalize_or_cap(metric, "/api/v1/agent/another_unseen_path")
    assert l7 == "_overflow_"
    assert over7 is True

    # Repeated observation of previously tracked label beta -> NOT overflow
    l_repeat, over_repeat = governor.normalize_or_cap(metric, "/api/v1/agent/beta")
    assert l_repeat == "/api/v1/agent/beta"
    assert over_repeat is False

    # Verify statistics
    stats = governor.get_metric_stats(metric)
    assert len(stats) == 1
    stat = stats[0]
    assert stat.cap_limit == 5
    assert stat.tracked_cardinality == 5
    assert stat.overflow_count == 2
    assert stat.total_samples == 8
    assert stat.status == CardinalityStatus.OVERFLOWING
    assert "_overflow_" in stat.top_tracked_labels


def test_custom_cap_configuration_and_reset(governor: MetricCardinalityGovernor) -> None:
    custom_metric = "model_fallback_events_total"
    governor.configure_cap(custom_metric, 2)

    g1, o1 = governor.normalize_or_cap(custom_metric, "gpt-4o")
    g2, o2 = governor.normalize_or_cap(custom_metric, "claude-3-5-sonnet")
    assert not o1 and not o2

    # 3rd label should overflow due to cap of 2
    g3, o3 = governor.normalize_or_cap(custom_metric, "deepseek-r1")
    assert g3 == "_overflow_"
    assert o3 is True

    # Reset
    governor.reset()
    stats = governor.get_metric_stats()
    assert len(stats) == 0

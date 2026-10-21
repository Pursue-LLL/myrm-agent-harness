"""
[INPUT]:
- ActiveSkillSpanProcessor, bind_active_skill, get_active_skill, set_active_skill, reset_active_skill

[OUTPUT]:
- Pytest verification for active skill ContextVar propagation, span attribute injection, and per-skill latency aggregation.

[POS]:
tests/observability/test_active_skill_telemetry.py — 活跃技能 Span 遥测处理器单元测试。
"""

import pytest

from myrm_agent_harness.observability.active_skill_telemetry import (
    ACTIVE_SKILL_ATTRIBUTE_KEY,
    COMPAT_SKILL_ATTRIBUTE_KEY,
    ActiveSkillSpanProcessor,
    ActiveSkillTelemetryReport,
    bind_active_skill,
    get_active_skill,
    reset_active_skill,
    set_active_skill,
)


def test_active_skill_contextvar_binding_and_nesting() -> None:
    assert get_active_skill() is None

    # 1. Single context manager binding
    with bind_active_skill("git_master"):
        assert get_active_skill() == "git_master"

    assert get_active_skill() is None

    # 2. Nested binding restoration
    with bind_active_skill("outer_skill"):
        assert get_active_skill() == "outer_skill"
        with bind_active_skill("inner_skill"):
            assert get_active_skill() == "inner_skill"
        assert get_active_skill() == "outer_skill"

    assert get_active_skill() is None


def test_span_processor_automatic_attribute_injection() -> None:
    processor = ActiveSkillSpanProcessor()
    processor.reset()

    # 1. Start span within active skill context
    with bind_active_skill("data_analysis"):
        attrs = processor.on_span_start({"user.agent": "myrm-core"})
        assert attrs[ACTIVE_SKILL_ATTRIBUTE_KEY] == "data_analysis"
        assert attrs[COMPAT_SKILL_ATTRIBUTE_KEY] == "data_analysis"
        assert attrs["user.agent"] == "myrm-core"

        # Record span automatically inherits active skill from ContextVar
        record = processor.record_span(
            name="tool.sql_query",
            duration_ms=45.0,
            status="ok",
        )
        assert record.active_skill == "data_analysis"
        assert record.attributes[ACTIVE_SKILL_ATTRIBUTE_KEY] == "data_analysis"

    # 2. Start span without active skill context (unattributed baseline)
    unattributed_record = processor.record_span(
        name="system.heartbeat",
        duration_ms=5.0,
        status="ok",
    )
    assert unattributed_record.active_skill is None
    assert ACTIVE_SKILL_ATTRIBUTE_KEY not in unattributed_record.attributes


def test_per_skill_latency_aggregation_and_p95_percentiles() -> None:
    processor = ActiveSkillSpanProcessor()
    processor.reset()

    # Record 10 spans for git_master
    with bind_active_skill("git_master"):
        for i in range(1, 11):
            processor.record_span(
                name="git.commit",
                duration_ms=float(i * 10),  # 10ms to 100ms
                status="error" if i == 10 else "ok",
            )

    # Record 5 spans for code_reviewer
    with bind_active_skill("code_reviewer"):
        for i in range(1, 6):
            processor.record_span(
                name="llm.review",
                duration_ms=float(i * 20),  # 20ms to 100ms
                status="ok",
            )

    # Record 2 unattributed spans
    processor.record_span(name="auth.check", duration_ms=2.0)
    processor.record_span(name="config.load", duration_ms=4.0)

    report = processor.get_report()
    assert report.total_spans_recorded == 17
    assert report.skills_count == 2
    assert report.unattributed_spans_count == 2

    # Check git_master stats
    git_stats = next(a for a in report.skill_aggregations if a.skill_name == "git_master")
    assert git_stats.total_spans == 10
    assert git_stats.error_spans == 1
    assert git_stats.error_rate == 0.1
    assert git_stats.p95_duration_ms == 100.0

    # Check code_reviewer stats
    reviewer_stats = next(a for a in report.skill_aggregations if a.skill_name == "code_reviewer")
    assert reviewer_stats.total_spans == 5
    assert reviewer_stats.error_spans == 0
    assert reviewer_stats.error_rate == 0.0

    # Test filtering and reset
    git_spans = processor.get_spans(skill_name="git_master")
    assert len(git_spans) == 10

    processor.reset()
    assert len(processor.get_spans()) == 0

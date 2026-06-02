"""Tests for loop_guard_stats — persistent loop event storage and analysis."""

from __future__ import annotations

import tempfile

import pytest

from myrm_agent_harness.agent.security.guards.loop_guard_stats import LoopGuardStatsDB
from myrm_agent_harness.agent.security.guards.loop_guard_types import LoopKind


@pytest.fixture
def db() -> LoopGuardStatsDB:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        return LoopGuardStatsDB(db_path=f.name)


class TestLoopGuardStatsDB:
    def test_init_creates_tables(self, db: LoopGuardStatsDB) -> None:
        assert db.db_path.exists()

    def test_record_event(self, db: LoopGuardStatsDB) -> None:
        db.record_event("bash_tool", LoopKind.REPETITION)
        stats = db.get_tool_stats(since_days=1)
        assert len(stats) == 1
        assert stats[0].tool_name == "bash_tool"
        assert stats[0].total_events == 1

    def test_record_event_with_args(self, db: LoopGuardStatsDB) -> None:
        db.record_event("bash_tool", LoopKind.REPETITION, args_sample={"cmd": "ls"}, severity="ERROR")
        stats = db.get_tool_stats(since_days=1)
        assert stats[0].total_events == 1

    def test_multiple_events(self, db: LoopGuardStatsDB) -> None:
        for _ in range(5):
            db.record_event("tool_a", LoopKind.REPETITION)
        for _ in range(3):
            db.record_event("tool_b", LoopKind.PING_PONG)
        stats = db.get_tool_stats(since_days=1)
        assert len(stats) == 2
        assert stats[0].total_events == 5
        assert stats[1].total_events == 3


class TestGetToolStats:
    def test_empty_db(self, db: LoopGuardStatsDB) -> None:
        stats = db.get_tool_stats(since_days=1)
        assert stats == []

    def test_percentage_calculation(self, db: LoopGuardStatsDB) -> None:
        for _ in range(10):
            db.record_event("tool_a", LoopKind.REPETITION)
        stats = db.get_tool_stats(since_days=1)
        assert stats[0].percentage_of_total == 100.0

    def test_configured_tools(self, db: LoopGuardStatsDB) -> None:
        db.record_event("tool_a", LoopKind.REPETITION)
        stats = db.get_tool_stats(since_days=1, configured_tools={"tool_a"})
        assert stats[0].is_configured is True

    def test_unconfigured_high_priority(self, db: LoopGuardStatsDB) -> None:
        for _ in range(20):
            db.record_event("tool_a", LoopKind.REPETITION)
        stats = db.get_tool_stats(since_days=1, configured_tools=set())
        assert "RECOMMEND" in stats[0].priority_recommendation

    def test_events_by_kind(self, db: LoopGuardStatsDB) -> None:
        db.record_event("tool_a", LoopKind.REPETITION)
        db.record_event("tool_a", LoopKind.REPETITION)
        db.record_event("tool_a", LoopKind.PING_PONG)
        stats = db.get_tool_stats(since_days=1)
        assert stats[0].events_by_kind["repetition"] == 2
        assert stats[0].events_by_kind["ping_pong"] == 1


class TestAnalyzeCoverage:
    def test_empty_db(self, db: LoopGuardStatsDB) -> None:
        analysis = db.analyze_coverage(configured_tools=set(), since_days=1)
        assert analysis.total_events == 0
        assert analysis.configured_coverage_rate == 0.0

    def test_full_coverage(self, db: LoopGuardStatsDB) -> None:
        for _ in range(10):
            db.record_event("tool_a", LoopKind.REPETITION)
        analysis = db.analyze_coverage(configured_tools={"tool_a"}, since_days=1)
        assert analysis.configured_coverage_rate == 1.0
        assert analysis.edge_contribution_rate == 0.0

    def test_partial_coverage(self, db: LoopGuardStatsDB) -> None:
        for _ in range(5):
            db.record_event("tool_a", LoopKind.REPETITION)
        for _ in range(5):
            db.record_event("tool_b", LoopKind.REPETITION)
        analysis = db.analyze_coverage(configured_tools={"tool_a"}, since_days=1)
        assert analysis.configured_coverage_rate == 0.5
        assert analysis.edge_contribution_rate == 0.5


class TestGenerateReport:
    def test_empty_report(self, db: LoopGuardStatsDB) -> None:
        report = db.generate_report(configured_tools=set(), since_days=1)
        assert "Statistics Report" in report
        assert "Total Events: 0" in report

    def test_report_with_data(self, db: LoopGuardStatsDB) -> None:
        for _ in range(15):
            db.record_event("tool_a", LoopKind.REPETITION)
        for _ in range(5):
            db.record_event("tool_b", LoopKind.PING_PONG)
        report = db.generate_report(configured_tools={"tool_a"}, since_days=1)
        assert "tool_a" in report
        assert "tool_b" in report
        assert "Total Events: 20" in report

    def test_report_recommendations(self, db: LoopGuardStatsDB) -> None:
        for _ in range(20):
            db.record_event("unconfigured_tool", LoopKind.REPETITION)
        report = db.generate_report(configured_tools=set(), since_days=1)
        assert "unconfigured_tool" in report


class TestClearOldEvents:
    def test_clear_keeps_recent(self, db: LoopGuardStatsDB) -> None:
        db.record_event("tool_a", LoopKind.REPETITION)
        deleted = db.clear_old_events(days_to_keep=1)
        assert deleted == 0
        stats = db.get_tool_stats(since_days=1)
        assert len(stats) == 1

    def test_clear_all(self, db: LoopGuardStatsDB) -> None:
        db.record_event("tool_a", LoopKind.REPETITION)
        deleted = db.clear_old_events(days_to_keep=0)
        assert deleted == 1

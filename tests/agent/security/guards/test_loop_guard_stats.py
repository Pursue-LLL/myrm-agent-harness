"""Unit tests for LoopGuardStatsDB persistent statistics layer."""

from __future__ import annotations

from datetime import datetime, timedelta

from myrm_agent_harness.agent.security.guards.loop_guard.stats import LoopGuardStatsDB
from myrm_agent_harness.agent.security.guards.loop_guard.types import LoopKind


def _insert_raw(db: LoopGuardStatsDB, tool: str, kind: str, timestamp: float) -> None:
    """Insert an event row directly (bypasses record_event for timestamp control)."""
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO loop_events (tool_name, loop_kind, timestamp, severity) VALUES (?, ?, ?, ?)",
            (tool, kind, timestamp, "WARNING"),
        )
        conn.commit()


def _old_timestamp(days: int) -> float:
    return (datetime.now() - timedelta(days=days)).timestamp()


class TestInitAndRecord:
    def test_init_creates_schema(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        assert db.db_path.exists()

    def test_record_event_with_args(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        db.record_event(
            "bash_code_execute_tool",
            LoopKind.REPETITION,
            args_sample={"command": "echo hi"},
        )
        with db._connect() as conn:
            row = conn.execute("SELECT tool_name, loop_kind FROM loop_events").fetchone()
        assert row == ("bash_code_execute_tool", "repetition")

    def test_record_event_without_args(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        db.record_event("file_read_tool", LoopKind.NO_PROGRESS)
        with db._connect() as conn:
            row = conn.execute("SELECT args_sample FROM loop_events WHERE tool_name=?", ("file_read_tool",)).fetchone()
        assert row[0] is None


class TestGetToolStats:
    def test_empty_db_returns_empty_list(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        assert db.get_tool_stats() == []

    def test_computes_percentage_and_priority(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        now = datetime.now().timestamp()
        for _ in range(9):
            _insert_raw(db, "tool_a", "repetition", now)
        _insert_raw(db, "tool_b", "no_progress", now)

        stats = db.get_tool_stats(configured_tools={"tool_a"})
        by_name = {s.tool_name: s for s in stats}
        assert by_name["tool_a"].percentage_of_total == 90.0
        assert by_name["tool_a"].is_configured is True
        assert by_name["tool_a"].priority_recommendation == "P0"
        assert by_name["tool_b"].is_configured is False
        assert by_name["tool_b"].priority_recommendation == "P0 - RECOMMEND ADD"

    def test_p1_and_p2_priority(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        now = datetime.now().timestamp()
        for _ in range(100):
            _insert_raw(db, "tool_p0", "repetition", now)
        for _ in range(5):
            _insert_raw(db, "tool_p1", "no_progress", now)
        _insert_raw(db, "tool_p2", "no_progress", now)

        stats = {s.tool_name: s for s in db.get_tool_stats()}
        assert "P0" in stats["tool_p0"].priority_recommendation
        assert "P1" in stats["tool_p1"].priority_recommendation
        assert stats["tool_p2"].priority_recommendation == "P2"

    def test_sorts_descending_by_events(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        now = datetime.now().timestamp()
        for _ in range(2):
            _insert_raw(db, "tool_low", "no_progress", now)
        for _ in range(7):
            _insert_raw(db, "tool_high", "repetition", now)
        stats = db.get_tool_stats()
        assert stats[0].tool_name == "tool_high"

    def test_respects_since_days_cutoff(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        _insert_raw(db, "recent", "no_progress", datetime.now().timestamp())
        _insert_raw(db, "ancient", "no_progress", _old_timestamp(60))
        stats = db.get_tool_stats(since_days=7)
        assert {s.tool_name for s in stats} == {"recent"}


class TestAnalyzeCoverage:
    def test_coverage_calculation(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        now = datetime.now().timestamp()
        for _ in range(7):
            _insert_raw(db, "configured_tool", "repetition", now)
        for _ in range(3):
            _insert_raw(db, "edge_tool", "no_progress", now)

        coverage = db.analyze_coverage({"configured_tool"})
        assert coverage.total_events == 10
        assert coverage.configured_events_count == 7
        assert coverage.unconfigured_events_count == 3
        assert coverage.configured_tools_count == 1
        assert coverage.unconfigured_tools_count == 1
        assert coverage.configured_coverage_rate == 0.7
        assert coverage.edge_contribution_rate == 0.3

    def test_empty_db_coverage_zeros(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        coverage = db.analyze_coverage(set())
        assert coverage.total_events == 0
        assert coverage.configured_coverage_rate == 0.0
        assert coverage.edge_contribution_rate == 0.0


class TestGenerateReport:
    def test_report_contains_sections(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        now = datetime.now().timestamp()
        _insert_raw(db, "tool_a", "repetition", now)
        report = db.generate_report({"tool_a"})
        assert "Loop Detection Statistics Report" in report
        assert "Coverage Summary" in report
        assert "Top Tools by Loop Events" in report
        assert "tool_a" in report
        assert "no immediate action" in report.lower()

    def test_report_gap_branch(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        now = datetime.now().timestamp()
        for _ in range(9):
            _insert_raw(db, "edge_tool", "no_progress", now)
        report = db.generate_report(set())
        assert "gaps" in report
        assert "Add immediately" in report

    def test_report_medium_priority_branch(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        now = datetime.now().timestamp()
        for _ in range(100):
            _insert_raw(db, "main", "repetition", now)
        for _ in range(5):
            _insert_raw(db, "p1_tool", "no_progress", now)
        report = db.generate_report({"main"})
        assert "Consider adding" in report


class TestClearOldEvents:
    def test_deletes_only_old_events(self, tmp_path) -> None:
        db = LoopGuardStatsDB(tmp_path / "stats.db")
        _insert_raw(db, "old", "no_progress", _old_timestamp(45))
        _insert_raw(db, "new", "no_progress", datetime.now().timestamp())
        deleted = db.clear_old_events(days_to_keep=30)
        assert deleted == 1
        with db._connect() as conn:
            remaining = conn.execute("SELECT tool_name FROM loop_events").fetchall()
        assert [r[0] for r in remaining] == ["new"]

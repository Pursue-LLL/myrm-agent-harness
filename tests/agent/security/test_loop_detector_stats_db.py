"""Tests for loop guard statistics and data-driven configuration."""

import tempfile
from pathlib import Path

from myrm_agent_harness.agent.security.guards.loop_guard import LoopGuard
from myrm_agent_harness.agent.security.guards.loop_guard_stats import LoopGuardStatsDB
from myrm_agent_harness.agent.security.guards.loop_guard_types import LoopKind


class TestStatsDBBasic:
    """Test basic stats database operations."""

    def test_db_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = LoopGuardStatsDB(db_path)

            assert db.db_path.exists()

    def test_record_and_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = LoopGuardStatsDB(db_path)

            db.record_event("test_tool", LoopKind.REPETITION, {"arg": "value"}, "WARNING")

            stats = db.get_tool_stats(since_days=1)
            assert len(stats) == 1
            assert stats[0].tool_name == "test_tool"
            assert stats[0].total_events == 1

    def test_multiple_tools_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = LoopGuardStatsDB(db_path)

            for _ in range(10):
                db.record_event("high_freq_tool", LoopKind.REPETITION)
            for _ in range(3):
                db.record_event("low_freq_tool", LoopKind.NO_PROGRESS)

            stats = db.get_tool_stats(since_days=1)

            assert len(stats) == 2
            assert stats[0].tool_name == "high_freq_tool"
            assert stats[0].total_events == 10
            assert stats[1].tool_name == "low_freq_tool"
            assert stats[1].total_events == 3


class TestCoverageAnalysis:
    """Test coverage analysis functionality."""

    def test_coverage_calculation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = LoopGuardStatsDB(db_path)

            for _ in range(90):
                db.record_event("configured_tool", LoopKind.REPETITION)
            for _ in range(10):
                db.record_event("unconfigured_tool", LoopKind.NO_PROGRESS)

            configured = {"configured_tool"}
            analysis = db.analyze_coverage(configured, since_days=1)

            assert analysis.total_events == 100
            assert analysis.configured_tools_count == 1
            assert analysis.configured_events_count == 90
            assert abs(analysis.configured_coverage_rate - 0.9) < 0.01
            assert abs(analysis.edge_contribution_rate - 0.1) < 0.01

    def test_priority_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = LoopGuardStatsDB(db_path)

            for _ in range(70):
                db.record_event("p0_tool", LoopKind.REPETITION)
            for _ in range(20):
                db.record_event("p1_tool", LoopKind.NO_PROGRESS)
            for _ in range(2):
                db.record_event("p2_tool", LoopKind.PING_PONG)

            stats = db.get_tool_stats(since_days=1, configured_tools=set())

            p0_tool = next(s for s in stats if s.tool_name == "p0_tool")
            p1_tool = next(s for s in stats if s.tool_name == "p1_tool")
            p2_tool = next(s for s in stats if s.tool_name == "p2_tool")

            assert p0_tool.percentage_of_total > 70
            assert "P0" in p0_tool.priority_recommendation
            assert 20 < p1_tool.percentage_of_total < 25
            assert "P0" in p1_tool.priority_recommendation or "P1" in p1_tool.priority_recommendation
            assert p2_tool.percentage_of_total < 3
            assert "P2" in p2_tool.priority_recommendation


class TestIntegrationWithGuard:
    """Test integration between LoopGuard and StatsDB."""

    def test_guard_records_to_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            stats_db = LoopGuardStatsDB(db_path)
            guard = LoopGuard(warn_threshold=3, break_threshold=5, stats_db=stats_db, enable_stats=True)

            for _ in range(3):
                v = guard.pre_check("test_tool", {"arg": "value"})

            assert v.action != "allow"

            stats = stats_db.get_tool_stats(since_days=1)
            assert len(stats) == 1
            assert stats[0].tool_name == "test_tool"
            assert stats[0].total_events == 1

    def test_disabled_stats_no_recording(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            stats_db = LoopGuardStatsDB(db_path)
            guard = LoopGuard(warn_threshold=3, break_threshold=5, stats_db=stats_db, enable_stats=False)

            for _ in range(3):
                guard.pre_check("test_tool", {"arg": "value"})

            stats = stats_db.get_tool_stats(since_days=1)
            assert len(stats) == 0


class TestReportGeneration:
    """Test report generation functionality."""

    def test_generate_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = LoopGuardStatsDB(db_path)

            for _ in range(100):
                db.record_event("high_freq", LoopKind.REPETITION)
            for _ in range(20):
                db.record_event("medium_freq", LoopKind.NO_PROGRESS)

            configured = {"high_freq"}
            report = db.generate_report(configured, since_days=1)

            assert "high_freq" in report
            assert "medium_freq" in report
            assert "Coverage Summary" in report
            assert "%" in report

    def test_clear_old_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = LoopGuardStatsDB(db_path)

            for _ in range(10):
                db.record_event("test_tool", LoopKind.REPETITION)

            deleted = db.clear_old_events(days_to_keep=1000)

            assert deleted == 0

            stats = db.get_tool_stats(since_days=1000)
            assert len(stats) == 1
            assert stats[0].total_events == 10

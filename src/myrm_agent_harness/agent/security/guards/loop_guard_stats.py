"""Loop detection statistics and data-driven configuration.

Provides persistent storage and analysis of loop events to enable
data-driven decisions about which tools need suggestions.

[INPUT]
- loop_guard_types::LoopKind (POS: Core types for the unified loop guard. Provides verdict types (ALLOW/WARN/BREAK) and analysis types (SuccessLevel, AgentPhase, Metrics, etc.) for the LoopGuard detection system.)

[OUTPUT]
- LoopGuardStatsDB: persistent event storage and analysis
- ToolLoopStats: per-tool statistics
- CoverageAnalysis: coverage effectiveness metrics

[POS]
Optional persistent statistics layer for LoopGuard. Records loop events
to SQLite, analyzes tool-level loop frequency, and generates priority
recommendations for suggestion coverage.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .loop_guard_types import LoopKind


@dataclass
class ToolLoopStats:
    """Statistics for a single tool's loop behavior."""

    tool_name: str
    total_events: int
    events_by_kind: dict[str, int]
    percentage_of_total: float
    is_configured: bool
    priority_recommendation: str


@dataclass
class CoverageAnalysis:
    """Analysis of tool coverage effectiveness."""

    total_events: int
    configured_tools_count: int
    configured_events_count: int
    configured_coverage_rate: float
    unconfigured_tools_count: int
    unconfigured_events_count: int
    edge_contribution_rate: float


class LoopGuardStatsDB:
    """Persistent storage for loop detection events."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            default_dir = Path.home() / ".cache" / "myrm-agent-harness"
            default_dir.mkdir(parents=True, exist_ok=True)
            # DB filename kept for backward-compatibility with existing user data
            db_path = default_dir / "loop_detector_stats.db"

        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        from myrm_agent_harness.utils.db.sqlite import CACHE, harden_connection_sync

        conn = sqlite3.connect(self.db_path)
        harden_connection_sync(conn, CACHE, db_path=self.db_path)
        return conn

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS loop_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT NOT NULL,
                    loop_kind TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    args_sample TEXT,
                    severity TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tool_time
                ON loop_events(tool_name, timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_kind_time
                ON loop_events(loop_kind, timestamp)
            """)
            conn.commit()

    def record_event(
        self, tool_name: str, loop_kind: LoopKind, args_sample: dict[str, str] | None = None, severity: str = "WARNING"
    ) -> None:
        """Record a loop detection event."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO loop_events (tool_name, loop_kind, timestamp, args_sample, severity)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    tool_name,
                    loop_kind.value,
                    datetime.now().timestamp(),
                    json.dumps(args_sample, default=str) if args_sample else None,
                    severity,
                ),
            )
            conn.commit()

    def get_tool_stats(self, since_days: int = 7, configured_tools: set[str] | None = None) -> list[ToolLoopStats]:
        """Get loop statistics for each tool, sorted by total_events descending."""
        if configured_tools is None:
            configured_tools = set()

        cutoff_time = (datetime.now() - timedelta(days=since_days)).timestamp()

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tool_name, loop_kind, COUNT(*) as count
                FROM loop_events
                WHERE timestamp >= ?
                GROUP BY tool_name, loop_kind
                ORDER BY tool_name
                """,
                (cutoff_time,),
            ).fetchall()

            total_events_row = conn.execute(
                "SELECT COUNT(*) FROM loop_events WHERE timestamp >= ?", (cutoff_time,)
            ).fetchone()

        total_events = total_events_row[0] if total_events_row else 0

        tool_data: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for tool_name, loop_kind, count in rows:
            tool_data[tool_name][loop_kind] = count

        stats: list[ToolLoopStats] = []
        for tool_name, events_by_kind in tool_data.items():
            total_tool_events = sum(events_by_kind.values())
            percentage = (total_tool_events / total_events * 100) if total_events > 0 else 0.0
            is_configured = tool_name in configured_tools

            if percentage >= 10:
                priority = "P0"
            elif percentage >= 3:
                priority = "P1"
            else:
                priority = "P2"

            if not is_configured and priority in ("P0", "P1"):
                priority = f"{priority} - RECOMMEND ADD"

            stats.append(
                ToolLoopStats(
                    tool_name=tool_name,
                    total_events=total_tool_events,
                    events_by_kind=dict(events_by_kind),
                    percentage_of_total=percentage,
                    is_configured=is_configured,
                    priority_recommendation=priority,
                )
            )

        stats.sort(key=lambda s: s.total_events, reverse=True)
        return stats

    def analyze_coverage(self, configured_tools: set[str], since_days: int = 7) -> CoverageAnalysis:
        """Analyze the effectiveness of current tool coverage."""
        tool_stats = self.get_tool_stats(since_days, configured_tools)
        total_events = sum(s.total_events for s in tool_stats)

        configured_events = sum(s.total_events for s in tool_stats if s.is_configured)
        unconfigured_events = sum(s.total_events for s in tool_stats if not s.is_configured)

        configured_tools_count = sum(1 for s in tool_stats if s.is_configured)
        unconfigured_tools_count = sum(1 for s in tool_stats if not s.is_configured)

        configured_coverage = configured_events / total_events if total_events > 0 else 0.0
        edge_contribution = unconfigured_events / total_events if total_events > 0 else 0.0

        return CoverageAnalysis(
            total_events=total_events,
            configured_tools_count=configured_tools_count,
            configured_events_count=configured_events,
            configured_coverage_rate=configured_coverage,
            unconfigured_tools_count=unconfigured_tools_count,
            unconfigured_events_count=unconfigured_events,
            edge_contribution_rate=edge_contribution,
        )

    def generate_report(self, configured_tools: set[str], since_days: int = 7) -> str:
        """Generate a human-readable statistics report."""
        tool_stats = self.get_tool_stats(since_days, configured_tools)
        coverage = self.analyze_coverage(configured_tools, since_days)

        lines = [
            "=" * 80,
            f"Loop Detection Statistics Report - Last {since_days} Days",
            "=" * 80,
            "",
            "【Coverage Summary】",
            f" Total Events: {coverage.total_events}",
            f" Configured Tools: {coverage.configured_tools_count}",
            f" Configured Events: {coverage.configured_events_count} ({coverage.configured_coverage_rate:.1%})",
            f" Unconfigured Events: {coverage.unconfigured_events_count} ({coverage.edge_contribution_rate:.1%})",
            "",
            "=" * 80,
            "【Top Tools by Loop Events】",
            "=" * 80,
            "",
        ]

        for i, stat in enumerate(tool_stats[:15], 1):
            lines.append(
                f"{i:2}. {stat.tool_name:<30} "
                f"{stat.total_events:>6} events ({stat.percentage_of_total:>5.1f}%)  "
                f"[{stat.priority_recommendation}]"
            )
            kinds_str = ", ".join(f"{k}:{v}" for k, v in stat.events_by_kind.items())
            lines.append(f" Kinds: {kinds_str}")
            lines.append("")

        lines.extend(
            [
                "=" * 80,
                "【Recommendations】",
                "=" * 80,
                "",
            ]
        )

        needs_config = [s for s in tool_stats if not s.is_configured and s.priority_recommendation.startswith("P0")]
        if needs_config:
            lines.append(" High Priority - Add immediately:")
            for stat in needs_config:
                lines.append(f" - {stat.tool_name} ({stat.percentage_of_total:.1f}% of events)")
            lines.append("")

        needs_config_p1 = [s for s in tool_stats if not s.is_configured and s.priority_recommendation.startswith("P1")]
        if needs_config_p1:
            lines.append(" Medium Priority - Consider adding:")
            for stat in needs_config_p1:
                lines.append(f" - {stat.tool_name} ({stat.percentage_of_total:.1f}% of events)")
            lines.append("")

        if coverage.edge_contribution_rate < 0.05:
            lines.append(" Current coverage is excellent (>95% of events).")
            lines.append(" No immediate action needed.")
        elif coverage.edge_contribution_rate < 0.15:
            lines.append(" Current coverage is good (>85% of events).")
            lines.append(" Consider adding P1 tools if resources permit.")
        else:
            lines.append(" Current coverage has gaps (<85% of events).")
            lines.append(" Recommend adding high-priority tools.")

        lines.append("")
        return "\n".join(lines)

    def clear_old_events(self, days_to_keep: int = 30) -> int:
        """Delete events older than specified days. Returns number of deleted rows."""
        cutoff_time = (datetime.now() - timedelta(days=days_to_keep)).timestamp()

        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM loop_events WHERE timestamp < ?", (cutoff_time,))
            deleted = cursor.rowcount
            conn.commit()

        return deleted

"""Trace Analyzer for Skill Evolution.

[INPUT]
- agent.event_log.protocol::EventLogBackend (POS: Protocol contract. Framework provides FileEventLogBackend; business layer may extend with SQLite / PostgreSQL implementations.)
- agent.event_log.analytics_queries::get_session_summary (POS: Read-side analytics helpers for ``EventLogger``.)
- agent.event_log.analytics_queries::get_tool_usage_stats (POS: Read-side analytics helpers for ``EventLogger``.)
- agent.event_log.types::EventFilter (POS: Single source of truth for event log data structures.)

[OUTPUT]
- TraceAnalyzer: Extracts and formats full trajectories to inform LLM of exact failure steps.

[POS]
Trace Analyzer for Skill Evolution. Provides progressive disclosure analysis.
"""

import logging
import time
from typing import Any

from myrm_agent_harness.agent.event_log.analytics_queries import (
    get_session_summary,
    get_tool_usage_stats,
)
from myrm_agent_harness.agent.event_log.protocols import EventLogBackend
from myrm_agent_harness.agent.event_log.types import EventFilter
from myrm_agent_harness.agent.skills.evolution.core.types import SkillRecord

logger = logging.getLogger(__name__)


class TraceAnalyzer:
    """Extracts and formats full trajectories to inform LLM of exact failure steps.

    Provides progressive disclosure analysis (Overview -> Root Cause -> Tool Stats -> Error Details -> Benchmark Overview).
    """

    def __init__(self, backend: EventLogBackend) -> None:
        self._backend = backend

    async def analyze_slice(
        self, session_id: str, tool_call_ids: list[str]
    ) -> Any:
        """Analyze a specific slice of the execution trace.

        Args:
            session_id: The session ID
            tool_call_ids: List of specific tool call IDs that form the slice

        Returns:
            An object with `formatted_trace` and `is_coherent` properties, or None if failed.
        """
        from dataclasses import dataclass
        @dataclass
        class SliceResult:
            formatted_trace: str
            is_coherent: bool

        if not self._backend or not tool_call_ids:
            return None

        # Fetch events for the session
        # We fetch tool use events (pre/post/failure)
        events = await self._backend.get_events(
            session_id,
            EventFilter(
                event_types=frozenset(
                    {"pre_tool_use", "post_tool_use", "post_tool_use_failure"}
                )
            ),
        )

        if not events:
            return None

        # Filter events by the specific tool_call_ids
        slice_events = [evt for evt in events if evt.data.get("tool_call_id") in tool_call_ids]

        if not slice_events:
            return None

        # Format the trace for the LLM
        lines = []
        tool_call_count = 0
        error_count = 0
        last_tool = ""
        for evt in slice_events:
            if evt.event_type == "pre_tool_use":
                last_tool = evt.data.get("tool_name", "unknown")
                tool_input = evt.data.get("tool_input", {})
                lines.append(f"\n[Action] {last_tool}({tool_input})")
                tool_call_count += 1
            elif evt.event_type == "post_tool_use":
                lines.append(f"[Success] -> {str(evt.data.get('tool_output', ''))[:200]}...")
            elif evt.event_type == "post_tool_use_failure":
                lines.append(f"[Error] -> {str(evt.data.get('error', ''))[:200]}...")
                error_count += 1

        formatted_trace = "\n".join(lines)

        # AST / Coherence check
        # A coherent slice has at least 1 tool call and an error rate < 80% (not just endless failing loops)
        is_coherent = tool_call_count >= 1 and (error_count / max(1, tool_call_count)) < 0.8

        return SliceResult(formatted_trace=formatted_trace, is_coherent=is_coherent)

    async def extract_trajectory_with_code(
        self, session_id: str, skill: "SkillRecord", max_token_budget: int = 2500
    ) -> str:
        """Extract trajectory and include the skill's code context.

        This is a high-value optimization that provides the LLM with both the
        execution trace AND the actual code that failed, significantly improving
        root cause analysis accuracy.
        """
        # Get the base trajectory analysis
        trajectory = await self.extract_trajectory(
            session_id, skill.skill_id, max_token_budget=1500
        )

        # Append the code context
        code_context = f"\n\n## 技能代码上下文 (Skill Code Context)\n```python\n{skill.content}\n```\n"

        return trajectory + code_context

    async def extract_trajectory(
        self, session_id: str, skill_id: str, max_token_budget: int = 2000
    ) -> str:
        """Extract a formatted string of the execution trace leading to a failure.

        Args:
            session_id: The session where the failure occurred.
            skill_id: The skill that failed.
            max_token_budget: Maximum token budget for the output (approximate).

        Returns:
            A formatted markdown string showing the agent's step-by-step actions.
        """
        start_time = time.time()

        if not self._backend:
            return "Trace analysis unavailable (no EventLogBackend)."

        # 1. Get session overview (fetch all to get the latest timeline events)
        summary = await get_session_summary(
            self._backend, session_id, events_limit=10000, timeline_limit=10000
        )

        # 2. Get tool usage stats
        tool_stats = await get_tool_usage_stats(self._backend, session_id)

        # 3. Get error events (fetch all to get the latest errors)
        all_error_events = await self._backend.get_events(
            session_id,
            EventFilter(
                event_types=frozenset(
                    {"tool_error", "agent_error", "tool_timeout", "tool_failure"}
                )
            ),
        )
        # Take the last 20 errors
        error_events = all_error_events[-20:] if all_error_events else []

        # 4. Analyze failure mode
        failure_mode = self._analyze_failure_mode(summary, tool_stats, error_events)

        # 5. Format for LLM
        result = self._format_for_llm(
            summary=summary,
            tool_stats=tool_stats,
            error_events=error_events,
            failure_mode=failure_mode,
            skill_id=skill_id,
            max_tokens=max_token_budget,
        )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"TraceAnalyzer executed in {elapsed_ms:.1f}ms for session {session_id}"
        )

        return result

    def _analyze_failure_mode(self, summary, tool_stats, error_events) -> str:
        """Analyze failure mode (Root cause analysis)."""
        error_types = {}
        for evt in error_events:
            evt_type = evt.event_type
            error_types[evt_type] = error_types.get(evt_type, 0) + 1

        failure_reasons = {}
        for stat in tool_stats:
            for reason, count in stat.failure_reasons.items():
                failure_reasons[reason] = failure_reasons.get(reason, 0) + count

        if "tool_timeout" in error_types and error_types["tool_timeout"] > 3:
            return "timeout"
        elif any(
            "permission" in r.lower() or "403" in r.lower() for r in failure_reasons
        ):
            return "permission"
        elif "tool_error" in error_types or "tool_failure" in error_types:
            return "tool_error"
        else:
            return "unknown"

    def _cluster_similar_errors(self, error_events) -> dict[str, list]:
        """Cluster similar errors to reduce redundancy."""
        from difflib import SequenceMatcher

        clusters = {}
        for evt in error_events:
            error_msg = evt.data.get("error") or evt.data.get("error_code") or ""
            error_msg_str = str(error_msg)

            matched = False
            for cluster_key in clusters:
                if SequenceMatcher(None, cluster_key, error_msg_str).ratio() > 0.8:
                    clusters[cluster_key].append(evt)
                    matched = True
                    break

            if not matched:
                clusters[error_msg_str] = [evt]

        return clusters

    def _format_for_llm(
        self,
        summary,
        tool_stats,
        error_events,
        failure_mode: str,
        skill_id: str,
        max_tokens: int,
    ) -> str:
        """Format for LLM with progressive disclosure and token budget locking."""
        lines = []

        # 1. Overview
        lines.append("## 会话概览 (Session Overview)")
        lines.append(f"- 会话 ID: {summary.session_id}")
        lines.append(f"- 目标分析技能 (Target Skill): **{skill_id}**")
        lines.append(f"- 执行时长: {summary.duration_ms / 1000:.1f}s")
        lines.append(f"- 工具调用: {len(summary.tool_breakdown)} 个")

        if summary.token_economics:
            total_tokens = summary.token_economics.get("total_tokens", 0)
            lines.append(f"- Token 消耗: {total_tokens}")

        lines.append("")

        # 2. Root Cause Analysis
        lines.append("## 根因分析 (Per-task Analysis)")
        lines.append(f"**失败模式**: `{failure_mode}`")

        if failure_mode == "timeout":
            lines.append(" **可能原因**: 工具执行超时。")
            lines.append(" **修复建议**: 增加超时时间，或优化算法复杂度。")
        elif failure_mode == "permission":
            lines.append(" **可能原因**: 权限不足或被拒绝访问。")
            lines.append(" **修复建议**: 检查文件/目录权限，或检查 API 认证信息。")
        elif failure_mode == "tool_error":
            lines.append(" **可能原因**: 工具调用错误。")
            lines.append(
                " **修复建议**: 检查传入参数是否符合工具 schema，或检查逻辑漏洞。"
            )

        lines.append("")

        # 3. Tool Stats
        if tool_stats:
            lines.append("## 工具统计 (Tool Stats)")
            for stat in tool_stats[:5]:
                success_rate = (
                    stat.success_count / stat.total_calls if stat.total_calls > 0 else 0
                )
                marker = " (Target)" if stat.tool_name == skill_id else ""
                lines.append(
                    f"- **{stat.tool_name}**{marker}: "
                    f"{stat.total_calls} 次调用, "
                    f"成功率 {success_rate:.1%}, "
                    f"失败 {stat.failure_count} 次"
                )
            lines.append("")

        # 4. Error Details (Clustered)
        if error_events:
            lines.append("## 关键错误详情 (Error Details)")
            clusters = self._cluster_similar_errors(error_events)

            for i, (error_msg, evts) in enumerate(list(clusters.items())[:10]):
                if len(error_msg) > 200:
                    error_msg = error_msg[:200] + "...(truncated)"

                # Check if this error is related to the target skill
                is_target = any(e.data.get("tool_name") == skill_id for e in evts)
                marker = " " if is_target else ""

                lines.append(
                    f"{i+1}. [{evts[0].event_type}]{marker} (出现 {len(evts)} 次) {error_msg}"
                )
            lines.append("")

        # 5. Benchmark Overview
        lines.append("## 全局概览 (Benchmark-level Overview)")
        lines.append(f"- 总事件数: {len(summary.events_timeline)}")
        lines.append(f"- 错误总数: {len(error_events)}")
        if tool_stats:
            avg_success_rate = sum(
                s.success_count / s.total_calls if s.total_calls > 0 else 0
                for s in tool_stats
            ) / len(tool_stats)
            lines.append(f"- 平均成功率: {avg_success_rate:.1%}")

        # 6. Timeline (Brief)
        if summary.events_timeline:
            lines.append("\n## 执行时间线 (Timeline)")
            for evt in summary.events_timeline[-5:]:  # Last 5 events
                marker = " " if evt.data.get("tool_name") == skill_id else ""
                lines.append(
                    f"- {evt.event_type}: {evt.data.get('tool_name', '')}{marker}"
                )

        output = "\n".join(lines)

        # Token Locking (1 token ≈ 4 chars)
        estimated_tokens = len(output) // 4
        if estimated_tokens > max_tokens:
            max_chars = max_tokens * 4
            output = output[:max_chars] + "\n\n...(truncated to fit token budget)"

        return output

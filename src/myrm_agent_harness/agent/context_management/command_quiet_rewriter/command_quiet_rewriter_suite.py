"""Command Quiet Rewriter and Subagent Log Sink Suite.

Unified facade combining preflight quiet flag rewriting and isolated subagent
log sink blackhole quarantine for radical context window noise suppression.

[INPUT]
- agent.context_management.command_quiet_rewriter.preflight_command_rewriter::PreflightCommandRewriter (POS:
  Preflight Command Rewriter that intercepts CLI commands before sandbox execution.)
- agent.context_management.command_quiet_rewriter.quiet_rewriter_types::LogSinkConclusionCard, LogSinkStatus,
  LogSinkTaskSpec, LogSinkTaskType, QuietRewriteRule, RewriteResult, SubagentLogSinkExecutionRecord (POS: Data
  contracts and type definitions for preflight command rewriting and subagent log sink.)
- agent.context_management.command_quiet_rewriter.subagent_log_sink_engine::SubagentLogSinkEngine (POS:
  Subagent Log Sink Engine that absorbs massive process outputs into isolated contexts.)

[OUTPUT]
- CommandQuietRewriterAndLogSinkSuite: Master suite coordinating preflight command rewriting and subagent log
  sinks.

[POS]
Command Quiet Rewriter and Subagent Log Sink Suite.
"""

from __future__ import annotations

import re
from typing import Sequence

from .preflight_command_rewriter import PreflightCommandRewriter
from .quiet_rewriter_types import (
    LogSinkConclusionCard,
    LogSinkStatus,
    LogSinkTaskSpec,
    LogSinkTaskType,
    QuietRewriteRule,
    RewriteResult,
    SubagentLogSinkExecutionRecord,
)
from .subagent_log_sink_engine import SubagentLogSinkEngine


class CommandQuietRewriterAndLogSinkSuite:
    """Master suite coordinating preflight command rewriting and subagent log sinks."""

    def __init__(
        self,
        custom_rules: Sequence[QuietRewriteRule] | None = None,
        rewriter_enabled: bool = True,
    ) -> None:
        self._rewriter = PreflightCommandRewriter(custom_rules=custom_rules, enabled=rewriter_enabled)
        self._log_sink = SubagentLogSinkEngine()
        self._records: list[SubagentLogSinkExecutionRecord] = []
        self._rewrite_count = 0
        self._bypassed_count = 0

    @property
    def rewriter(self) -> PreflightCommandRewriter:
        """Access underlying preflight rewriter instance."""
        return self._rewriter

    @property
    def log_sink(self) -> SubagentLogSinkEngine:
        """Access underlying log sink engine instance."""
        return self._log_sink

    def rewrite_preflight(self, command: str) -> RewriteResult:
        """Inspect and rewrite command before sandbox invocation."""
        result = self._rewriter.rewrite(command)
        if result.was_modified:
            self._rewrite_count += 1
        else:
            self._bypassed_count += 1
        return result

    def should_delegate_to_log_sink(
        self,
        command_or_desc: str,
        expected_output_lines: int = 0,
    ) -> bool:
        """Determine if an operation is high-noise and should be delegated to a subagent sink."""
        if expected_output_lines > 100:
            return True

        lower_cmd = command_or_desc.lower()
        # High noise signals: full test suites, broad git log, large log dump
        high_noise_patterns = [
            r"pytest\s+(?:tests|test)\b(?!\s*-[k])",  # full test runs
            r"vitest\s+run\b",
            r"npm\s+test\b",
            r"(?:cat|tail|grep)\s+.*?\.(?:log|out|txt)\b",
            r"git\s+log\s+(?:--all|--branches|--graph)\b",
            r"(?:mvn|gradle)\s+(?:test|build)\b",
        ]

        return any(re.search(pat, lower_cmd) for pat in high_noise_patterns)

    def quarantine_and_distill(
        self,
        task_spec: LogSinkTaskSpec,
        raw_output: str,
        execution_duration_ms: float = 0.0,
        subagent_steps: int = 1,
    ) -> tuple[LogSinkConclusionCard, SubagentLogSinkExecutionRecord]:
        """Absorb voluminous output inside subagent blackhole and return distilled card."""
        card, record = self._log_sink.distill_and_quarantine(
            task_spec=task_spec,
            raw_output=raw_output,
            execution_duration_ms=execution_duration_ms,
            subagent_steps=subagent_steps,
        )
        self._records.append(record)
        return card, record

    def render_conclusion_card(self, card: LogSinkConclusionCard) -> str:
        """Format a distilled card into a 3-5 line Markdown summary for the main session."""
        status_icon = "✅" if card.status == LogSinkStatus.SUCCESS else "⚠️" if card.status == LogSinkStatus.PARTIAL else "❌"
        pct = int(card.noise_reduction_ratio * 100)

        lines: list[str] = [
            f"> {status_icon} **Subagent Log Sink [{card.task_type.value}]** (Suppressed {pct}% noise | {card.raw_character_count} chars absorbed):",
        ]
        for bullet in card.bullet_points:
            lines.append(f"> - {bullet}")

        if card.suggested_action:
            lines.append(f"> - *Action*: {card.suggested_action}")

        return "\n".join(lines)

    def get_aggregate_metrics(self) -> dict[str, object]:
        """Return cumulative telemetry on noise suppression across session."""
        total_raw_tokens = sum(r.raw_tokens_absorbed for r in self._records)
        total_delivered_tokens = sum(r.delivered_tokens for r in self._records)
        net_saved_tokens = max(0, total_raw_tokens - total_delivered_tokens)

        overall_ratio = 0.0
        if total_raw_tokens > 0:
            overall_ratio = net_saved_tokens / total_raw_tokens

        return {
            "commands_rewritten": self._rewrite_count,
            "commands_unmodified_or_bypassed": self._bypassed_count,
            "delegated_sink_tasks": len(self._records),
            "raw_tokens_absorbed_in_sink": total_raw_tokens,
            "tokens_delivered_to_main_session": total_delivered_tokens,
            "net_tokens_saved": net_saved_tokens,
            "noise_suppression_ratio": round(overall_ratio, 4),
        }

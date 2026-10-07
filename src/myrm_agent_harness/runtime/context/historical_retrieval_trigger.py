"""Monitors tool execution failures and actively suggests searching session archives when blind retries are detected.

[INPUT]
- runtime.context.historical_retrieval_trigger_types::HeuristicAnomalyKind, HeuristicTriggerResult,
  ToolExecutionFeedback

[OUTPUT]
- HistoricalRetrievalHeuristicTrigger: Monitors tool execution failures and actively suggests searching
  session archives when blind retries are detected.

[POS]
Monitors tool execution failures and actively suggests searching session archives when blind retries are
detected.
"""

from __future__ import annotations

import re

from myrm_agent_harness.runtime.context.historical_retrieval_trigger_types import (
    HeuristicAnomalyKind,
    HeuristicTriggerResult,
    ToolExecutionFeedback,
)


class HistoricalRetrievalHeuristicTrigger:
    """Monitors tool execution failures and actively suggests searching session archives when blind retries are detected."""

    AUTH_KEYWORDS = ("api_key", "token", "unauthorized", "401", "auth", "permission denied", "forbidden", "403")
    CONFIG_KEYWORDS = ("not found", "404", "no such file", "config", "settings", "does not exist")
    PARAM_KEYWORDS = ("missing argument", "missing parameter", "keyerror", "undefined", "invalid parameter")

    def __init__(self, failure_threshold: int = 2) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self._consecutive_failures = 0

    @property
    def consecutive_failures(self) -> int:
        """Current count of consecutive tool execution failures."""
        return self._consecutive_failures

    def reset(self) -> None:
        """Reset consecutive failure count to zero."""
        self._consecutive_failures = 0

    def record_tool_result(self, feedback: ToolExecutionFeedback) -> HeuristicTriggerResult:
        """Record the outcome of a tool call and evaluate if retrieval heuristics should trigger."""
        if feedback.success:
            self._consecutive_failures = 0
            return HeuristicTriggerResult(
                triggered=False,
                consecutive_failures=0,
                matched_anomaly_kind=None,
                suggested_query_terms=[],
                system_hint_block=None,
                message="Tool execution succeeded; consecutive failure counter reset.",
            )

        self._consecutive_failures += 1
        err_msg = (feedback.error_message or "").lower()

        # Classify anomaly kind
        anomaly: HeuristicAnomalyKind = HeuristicAnomalyKind.CONSECUTIVE_ERRORS
        if any(kw in err_msg for kw in self.AUTH_KEYWORDS):
            anomaly = HeuristicAnomalyKind.AUTH_CREDENTIAL_MISSING
        elif any(kw in err_msg for kw in self.CONFIG_KEYWORDS):
            anomaly = HeuristicAnomalyKind.CONFIG_NOT_FOUND
        elif any(kw in err_msg for kw in self.PARAM_KEYWORDS):
            anomaly = HeuristicAnomalyKind.PARAMETER_MISSING

        # Extract suggested search query terms from error details
        suggested_terms = self._extract_suggested_terms(feedback.tool_name, feedback.error_message)

        # Trigger if failures reached threshold or specific missing-configuration anomaly occurred
        should_trigger = self._consecutive_failures >= self.failure_threshold or anomaly in (
            HeuristicAnomalyKind.AUTH_CREDENTIAL_MISSING,
            HeuristicAnomalyKind.CONFIG_NOT_FOUND,
        )

        if not should_trigger:
            return HeuristicTriggerResult(
                triggered=False,
                consecutive_failures=self._consecutive_failures,
                matched_anomaly_kind=anomaly,
                suggested_query_terms=suggested_terms,
                system_hint_block=None,
                message=f"Recorded failure {self._consecutive_failures}/{self.failure_threshold}.",
            )

        hint_block = self._format_hint_block(
            failures=self._consecutive_failures,
            anomaly=anomaly,
            suggested_terms=suggested_terms,
        )

        return HeuristicTriggerResult(
            triggered=True,
            consecutive_failures=self._consecutive_failures,
            matched_anomaly_kind=anomaly,
            suggested_query_terms=suggested_terms,
            system_hint_block=hint_block,
            message="Heuristic retrieval triggered to prevent blind trial-and-error loops.",
        )

    def _extract_suggested_terms(self, tool_name: str, error_message: str | None) -> list[str]:
        terms: list[str] = [tool_name]
        if not error_message:
            return terms

        # Extract quoted substrings (e.g. 'file.txt' or "API_KEY")
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", error_message)
        for q in quoted:
            if len(q.strip()) > 2 and q not in terms:
                terms.append(q.strip())

        # Extract path-like or variable-like tokens
        tokens = re.findall(r"\b[A-Za-z0-9_]{3,}\b", error_message)
        for t in tokens:
            if t.lower() not in {"error", "failed", "exception", "none", "true", "false"} and t not in terms:
                terms.append(t)
            if len(terms) >= 5:
                break

        return terms[:5]

    @staticmethod
    def _format_hint_block(failures: int, anomaly: HeuristicAnomalyKind, suggested_terms: list[str]) -> str:
        terms_display = ", ".join(f"'{t}'" for t in suggested_terms)
        return (
            f'<system_heuristic_retrieval_hint consecutive_failures="{failures}" anomaly="{anomaly.value}">\n'
            f"[SYSTEM HEURISTIC TRIGGER] Multiple consecutive tool errors detected ({failures} failures).\n"
            f"- 建议措施: 当前工具调用反复报错，切勿凭空猜测参数盲目重试！\n"
            f"- 推荐操作: 请主动调用元工具 'search_session_archive'，尝试检索关键词: [{terms_display}]，以核实早期用户指令、密钥或配置参数。\n"
            f"</system_heuristic_retrieval_hint>"
        )

"""Adaptive risk-triggered router for MoA advisor overlay.

Evaluates multi-dimensional execution risk signals to decide whether reference
models (advisors) should be triggered to assist the acting model.

[INPUT]
- agent.middlewares.replan_middleware::get_max_consecutive_replan_errors
- agent.middlewares.tooling.tool_interceptor_middleware::get_loop_guard
- toolkits.llms.consensus.moa_overlay_types::MoAOverlayConfig

[OUTPUT]
- RiskTriggerReason: Enum of risk trigger causes
- RiskTriggerDecision: Structured decision with should_trigger, reason, score, detail
- is_unrecoverable_fatal_error: Helper to bypass advisor on fatal infrastructure errors
- AdvisorRiskTriggerRouter: Session-scoped risk evaluation router with cooldown and quota gates

[POS]
Pure middleware layer component. Inspects ReplanMiddleware and LoopGuard without
mutating them. Adheres strictly to toolkits/_ARCH.md by keeping agent awareness
out of the toolkits layer.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from langchain_core.messages import BaseMessage, ToolMessage

from myrm_agent_harness.agent.middlewares.replan_middleware import (
    get_max_consecutive_replan_errors,
    get_replan_error_summary,
)
from myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware import (
    get_loop_guard,
)
from myrm_agent_harness.agent.security.guards.loop_guard.types import LoopKind
from myrm_agent_harness.toolkits.llms.consensus.moa_overlay_types import (
    MoAOverlayConfig,
)

logger = logging.getLogger(__name__)

_FATAL_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:401|403)\b", re.IGNORECASE),
    re.compile(r"\b(?:unauthorized|forbidden|permission\s*denied)\b", re.IGNORECASE),
    re.compile(r"\b(?:enospc|no\s+space\s+left\s+on\s+device)\b", re.IGNORECASE),
    re.compile(r"\b(?:econnrefused|connection\s+refused)\b", re.IGNORECASE),
)


def is_unrecoverable_fatal_error(error_text: str) -> bool:
    """Detect if an error is a physical environment or auth failure that cannot be self-repaired."""
    if not error_text:
        return False
    return any(pat.search(error_text) is not None for pat in _FATAL_ERROR_PATTERNS)


class RiskTriggerReason(StrEnum):
    """Reason for triggering or bypassing advisor overlay under risk policy."""

    CONSECUTIVE_TOOL_FAILURES = "consecutive_tool_failures"
    LOOP_GUARD_WARNING = "loop_guard_warning"
    MULTI_TOOL_FAILURES = "multi_tool_failures"
    UNRECOVERABLE_FATAL_ERROR = "unrecoverable_fatal_error"


@dataclass(frozen=True, slots=True)
class RiskTriggerDecision:
    """Structured result of risk evaluation."""

    should_trigger: bool
    reason: RiskTriggerReason | None = None
    detail: str = ""
    risk_score: float = 0.0


class AdvisorRiskTriggerRouter:
    """Evaluates agent execution telemetry to gate MoA advisor fan-out under risk_triggered mode.

    Guards against excessive advisor invocation via:
    1. Fatal Error Bypass: 401/403/ENOSPC/ECONNREFUSED errors skip advisor to prevent token waste.
    2. Cooldown Window: Enforces `immune_turns` cooldown after each advisor activation.
    3. Session Quota: Enforces `max_per_session` trigger ceiling per session.
    """

    def __init__(self, config: MoAOverlayConfig | None = None) -> None:
        self._config = config or MoAOverlayConfig()
        self._last_trigger_turn: int = -999
        self._triggers_count: int = 0

    @property
    def triggers_count(self) -> int:
        """Total number of times the advisor was triggered in this session."""
        return self._triggers_count

    @property
    def last_trigger_turn(self) -> int:
        """Iteration index of the last advisor trigger."""
        return self._last_trigger_turn

    def reset(self) -> None:
        """Reset trigger counters and cooldown state."""
        self._last_trigger_turn = -999
        self._triggers_count = 0

    def record_trigger(self, turn_index: int) -> None:
        """Record an advisor activation at the given turn index."""
        self._last_trigger_turn = turn_index
        self._triggers_count += 1
        logger.info(
            "AdvisorRiskTriggerRouter: recorded trigger #%d at turn %d",
            self._triggers_count,
            turn_index,
        )

    def _extract_recent_error_text(self, messages: Sequence[BaseMessage] | None) -> str:
        if not messages:
            return ""
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage) and (msg.status == "error" or "error" in type(msg).__name__.lower()):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                return content
        return ""

    def evaluate_trigger(
        self,
        messages: Sequence[BaseMessage] | None = None,
        current_turn: int = 0,
    ) -> RiskTriggerDecision:
        """Evaluate whether to activate the MoA advisor overlay for the upcoming acting model call."""
        # 1. Hard Quota Check
        if self._triggers_count >= self._config.risk_trigger_max_per_session:
            return RiskTriggerDecision(
                should_trigger=False,
                detail=f"Session trigger quota reached ({self._config.risk_trigger_max_per_session})",
                risk_score=0.0,
            )

        # 2. Cooldown / Immunity Window Check
        turns_since_last = current_turn - self._last_trigger_turn
        if turns_since_last < self._config.risk_trigger_immune_turns:
            return RiskTriggerDecision(
                should_trigger=False,
                detail=(
                    f"Immune cooldown active ({turns_since_last}/"
                    f"{self._config.risk_trigger_immune_turns} turns elapsed)"
                ),
                risk_score=0.0,
            )

        # 3. Fatal Error Bypass
        recent_err = self._extract_recent_error_text(messages)
        if is_unrecoverable_fatal_error(recent_err):
            logger.info("AdvisorRiskTriggerRouter: bypass advisor due to unrecoverable fatal error")
            return RiskTriggerDecision(
                should_trigger=False,
                reason=RiskTriggerReason.UNRECOVERABLE_FATAL_ERROR,
                detail=f"Unrecoverable physical/auth error: {recent_err[:120]}",
                risk_score=0.0,
            )

        # 4. Check ReplanMiddleware error state
        max_replan_errors = get_max_consecutive_replan_errors()
        if max_replan_errors >= self._config.risk_trigger_failure_threshold:
            score = min(1.0, 0.5 + 0.2 * max_replan_errors)
            return RiskTriggerDecision(
                should_trigger=True,
                reason=RiskTriggerReason.CONSECUTIVE_TOOL_FAILURES,
                detail=f"Tool failed {max_replan_errors} times consecutively (threshold={self._config.risk_trigger_failure_threshold})",
                risk_score=score,
            )

        summary = get_replan_error_summary()
        failing_tools_count = sum(1 for count in summary.values() if count > 0)
        if failing_tools_count >= 2:
            return RiskTriggerDecision(
                should_trigger=True,
                reason=RiskTriggerReason.MULTI_TOOL_FAILURES,
                detail=f"Multiple tools ({failing_tools_count}) encountered errors: {list(summary.keys())}",
                risk_score=0.75,
            )

        # 5. Check LoopGuard telemetry
        guard = get_loop_guard()
        if guard is not None:
            last_kind = guard.last_detection_kind
            if last_kind and last_kind != LoopKind.OK.value:
                return RiskTriggerDecision(
                    should_trigger=True,
                    reason=RiskTriggerReason.LOOP_GUARD_WARNING,
                    detail=f"LoopGuard detected anomaly pattern: {last_kind}",
                    risk_score=0.9,
                )

            metrics = guard.get_metrics()
            if metrics.total_detections > 0:
                return RiskTriggerDecision(
                    should_trigger=True,
                    reason=RiskTriggerReason.LOOP_GUARD_WARNING,
                    detail=f"LoopGuard detected {metrics.total_detections} anomaly pattern(s)",
                    risk_score=0.85,
                )


        # 6. Check messages for consecutive ToolMessage errors
        if messages:
            streak = 0
            for msg in reversed(messages):
                if isinstance(msg, ToolMessage):
                    if msg.status == "error":
                        streak += 1
                    else:
                        break
                elif streak > 0:
                    break

            if streak >= self._config.risk_trigger_failure_threshold:
                return RiskTriggerDecision(
                    should_trigger=True,
                    reason=RiskTriggerReason.CONSECUTIVE_TOOL_FAILURES,
                    detail=f"Consecutive ToolMessage errors in history: {streak}",
                    risk_score=min(1.0, 0.5 + 0.2 * streak),
                )

        return RiskTriggerDecision(
            should_trigger=False,
            detail="Execution within nominal bounds; no risk condition breached",
            risk_score=0.0,
        )


__all__ = [
    "AdvisorRiskTriggerRouter",
    "RiskTriggerDecision",
    "RiskTriggerReason",
    "is_unrecoverable_fatal_error",
]

from __future__ import annotations

from collections.abc import Coroutine
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from langchain_core.messages import BaseMessage

if TYPE_CHECKING:
    from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary


class PreCompactAction(StrEnum):
    """Action decision before context compaction executes.

    CANCEL: Skip/delay compaction for this turn (e.g. during atomic multi-step generation).
    REPLACE: Use an external / cheap-model structured summary, skipping the expensive LLM run.
    PASSTHROUGH: Fall back to standard built-in compaction logic.
    """

    CANCEL = "cancel"
    REPLACE = "replace"
    PASSTHROUGH = "passthrough"


@dataclass(frozen=True, slots=True)
class PreCompactInjection:
    """Result of a pre-compaction semantic memory recall."""

    message: BaseMessage
    recalled_ids: tuple[str, ...]
    token_estimate: int
    query: str
    compaction_tier: str


@dataclass(frozen=True, slots=True)
class PreCompactDecision:
    """Pre-compaction three-state control decision.

    Attributes:
        action: The three-state action (CANCEL / REPLACE / PASSTHROUGH).
        replacement_summary: If action == REPLACE, the structured summary to use directly.
        injection: Optional semantic memory recall injection to preserve durable context.
        reason: Diagnostic reason for the decision.
    """

    action: PreCompactAction = PreCompactAction.PASSTHROUGH
    replacement_summary: StructuredSummary | None = None
    injection: PreCompactInjection | None = None
    reason: str = ""


class ContextPreCompactCallback(Protocol):
    """Pre-compaction memory recall and lifecycle interception callback.

    Invoked before Compress / SessionNotes / Summarize mutates the message list.
    Returns:
      - PreCompactDecision: Full three-state control (Cancel / Replace / Passthrough)
      - PreCompactInjection: Legacy semantic memory injection (automatically promoted to Passthrough)
      - None: Standard passthrough with no injection
    """

    def __call__(
        self,
        *,
        messages: list[BaseMessage],
        chat_id: str | None,
        user_id: str | None,
        compaction_tier: str,
        token_pressure_ratio: float,
        user_goal_hint: str,
    ) -> Coroutine[object, object, PreCompactDecision | PreCompactInjection | None]: ...


def normalize_pre_compact_decision(
    result: PreCompactDecision | PreCompactInjection | None,
) -> PreCompactDecision:
    """Normalize any callback result into a canonical PreCompactDecision."""
    if result is None:
        return PreCompactDecision(action=PreCompactAction.PASSTHROUGH)
    if isinstance(result, PreCompactDecision):
        return result
    if isinstance(result, PreCompactInjection):
        return PreCompactDecision(
            action=PreCompactAction.PASSTHROUGH,
            injection=result,
            reason="legacy_pre_compact_injection",
        )
    return PreCompactDecision(action=PreCompactAction.PASSTHROUGH)


PRE_COMPACT_MESSAGE_METADATA_KEY = "pre_compact_message"
PRE_COMPACT_INJECTION_METADATA_KEY = "pre_compact_injection"
PRE_COMPACT_DECISION_METADATA_KEY = "pre_compact_decision"
CANCEL_COMPACTION_METADATA_KEY = "cancel_compaction"
PRE_COMPACT_REPLACEMENT_SUMMARY_METADATA_KEY = "pre_compact_replacement_summary"


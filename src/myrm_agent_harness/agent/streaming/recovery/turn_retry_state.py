"""TurnRetryState: per-attempt/per-turn recovery guards and state tracking.

Encapsulates recovery state into a single strongly-typed dataclass,
eliminating mutable scattered local variables and preventing state leakage
across multiple turns or concurrent subagent runs.

[INPUT]
- (none)

[OUTPUT]
- TurnRetryState: Dataclass tracking one-shot recovery guards and restart signals.

[POS]
Per-turn retry and recovery bookkeeping for the streaming execution engine.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class TurnRetryState:
    """One-shot recovery guards and restart signals for a streaming API-call attempt.

    A fresh instance is bound to StreamContext per API attempt; each guard fires
    at most once, preventing infinite recovery loops and preserving prompt cache keys.
    Frozen immutable to eliminate mutable side-effects across coroutines or tasks.
    """

    # Format / Payload recovery guards
    reasoning_mandatory_attempted: bool = False
    thinking_sig_attempted: bool = False
    duplicate_tool_use_id_attempted: bool = False
    image_shrink_attempted: bool = False
    media_rejected_attempted: bool = False
    allowed_tools_rejected_attempted: bool = False
    long_context_tier_attempted: bool = False

    # Inference parameter recovery state (preserves Prompt Cache Key)
    reasoning_floor_required: bool = False
    reasoning_effort_overridden: bool = False
    active_reasoning_effort: str | None = None

    # Transient / PAAS overload state
    has_retried_paas_1305: bool = False
    paas_1305_retries: int = 0

    # Restart signals
    restart_with_rebuilt_request: bool = False
    restart_with_compacted_messages: bool = False

    def with_reasoning_floor(self, effort: str = "low") -> TurnRetryState:
        """Return a new instance with reasoning floor applied."""
        return replace(
            self,
            reasoning_mandatory_attempted=True,
            reasoning_floor_required=True,
            reasoning_effort_overridden=True,
            active_reasoning_effort=effort,
        )

    def with_paas_1305_incremented(self) -> TurnRetryState:
        """Return a new instance with PAAS 1305 retry counter incremented."""
        return replace(
            self,
            has_retried_paas_1305=True,
            paas_1305_retries=self.paas_1305_retries + 1,
        )

    def reset_attempt_transients(self) -> TurnRetryState:
        """Return a new instance with transient restart signals reset."""
        return replace(
            self,
            restart_with_rebuilt_request=False,
            restart_with_compacted_messages=False,
        )

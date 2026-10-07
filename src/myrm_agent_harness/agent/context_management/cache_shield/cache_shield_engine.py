"""Engine for prompt cache break interception, non-destructive branching, and tail rewinding.

[INPUT]
- agent.context_management.cache_shield.cache_break_evaluator::evaluate_parameter_mutation (POS: Detects
  mid-flight parameter mutations that break provider cache keys, calculating cost penalties and advice.)
- agent.context_management.cache_shield.cache_shield_types::CacheBreakEvaluation, CacheParameterKind,
  CachePreservingForkResult, CacheRewindResult (POS: Data contracts for cache break interception, cost impact
  evaluation, and smart cache branching.)

[OUTPUT]
- CacheBreakPreventionShieldEngine: Manages parameter interception, cache-preserving forking, and tail rewinds.

[POS]
Main coordinator protecting prompt cache keys from accidental destruction and supporting lossless rewinds.
"""

from __future__ import annotations

import logging
import uuid
from typing import Mapping, Sequence

from .cache_break_evaluator import evaluate_parameter_mutation
from .cache_shield_types import (
    CacheBreakEvaluation,
    CacheParameterKind,
    CachePreservingForkResult,
    CacheRewindResult,
)

logger = logging.getLogger(__name__)


class CacheBreakPreventionShieldEngine:
    """Manages prompt cache protection shields, cache-preserving branching, and tail-only rewinds."""

    def __init__(self, cache_alert_threshold: int = 8000) -> None:
        self._cache_alert_threshold = cache_alert_threshold
        self._active_evaluations: list[CacheBreakEvaluation] = []

    def intercept_parameter_change(
        self,
        session_id: str,
        param_kind: CacheParameterKind,
        old_value: str,
        new_value: str,
        current_tokens: int,
    ) -> CacheBreakEvaluation:
        """Evaluate mid-session parameter mutation and generate an advisory or blocking alert.

        Warns users when switching model or effort would wipe significant cached tokens,
        recommending a branch fork instead of destructive in-place modification.
        """
        evaluation = evaluate_parameter_mutation(
            param_kind=param_kind,
            old_value=old_value,
            new_value=new_value,
            current_tokens=current_tokens,
            cache_alert_threshold=self._cache_alert_threshold,
        )
        self._active_evaluations.append(evaluation)

        logger.info(
            "Session '%s' parameter mutation (%s: %s -> %s, %d tokens) evaluated as %s",
            session_id,
            param_kind.value,
            old_value,
            new_value,
            current_tokens,
            evaluation.risk_level.value,
        )
        return evaluation

    def fork_branch_with_cache_preservation(
        self,
        session_id: str,
        source_branch_id: str,
        fork_anchor_turn: int,
        current_cached_tokens: int,
        antecedent_summary: str | None = None,
    ) -> CachePreservingForkResult:
        """Fork a new child session branch with clean model configuration while preserving the original cache.

        Instead of mutating the parent session and wiping its prompt cache,
        this operation spawns a sibling branch with a synthesized summary,
        leaving the parent cache intact in the cloud provider.
        """
        new_branch_id = f"br-fork-{uuid.uuid4().hex[:8]}"
        summary = (
            antecedent_summary
            or f"Forked from branch '{source_branch_id}' at turn {fork_anchor_turn}. Upstream parent cache intact."
        )

        result = CachePreservingForkResult(
            new_branch_id=new_branch_id,
            source_branch_id=source_branch_id,
            fork_anchor_turn=fork_anchor_turn,
            preserved_cache_tokens=current_cached_tokens,
            transition_summary=summary,
        )

        logger.info(
            "Created cache-preserving fork '%s' from '%s' at turn %d (%d tokens preserved)",
            new_branch_id,
            source_branch_id,
            fork_anchor_turn,
            current_cached_tokens,
        )
        return result

    def rewind_tail_turns(
        self,
        session_id: str,
        messages: Sequence[Mapping[str, str]],
        turns_to_drop: int,
        estimated_token_per_turn: int = 500,
    ) -> tuple[CacheRewindResult, tuple[dict[str, str], ...]]:
        """Rewind history by dropping trailing turns only, ensuring 100% prefix cache match.

        Unlike rewriting or deleting historical turns in the middle, dropping turns
        from the tail preserves the exact byte prefix of earlier turns, guaranteeing
        that the next prompt hits the upstream prompt cache.
        """
        total = len(messages)
        if turns_to_drop <= 0 or total == 0:
            return (
                CacheRewindResult(
                    session_id=session_id,
                    dropped_turns_count=0,
                    retained_turns_count=total,
                    cache_prefix_intact=True,
                    retained_cache_tokens_estimate=total * estimated_token_per_turn,
                ),
                tuple(dict(m) for m in messages),
            )

        actual_drop = min(total, turns_to_drop)
        retained_messages = tuple(dict(m) for m in messages[: total - actual_drop])
        retained_count = len(retained_messages)

        result = CacheRewindResult(
            session_id=session_id,
            dropped_turns_count=actual_drop,
            retained_turns_count=retained_count,
            cache_prefix_intact=True,  # Byte prefix untouched!
            retained_cache_tokens_estimate=retained_count * estimated_token_per_turn,
        )

        logger.info(
            "Rewound session '%s': dropped %d trailing turns, retained %d turns with intact cache prefix",
            session_id,
            actual_drop,
            retained_count,
        )
        return result, retained_messages

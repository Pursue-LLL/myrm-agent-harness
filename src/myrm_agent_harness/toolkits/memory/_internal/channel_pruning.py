"""Channel pruning and sub-graph dispatch coordinator for memory retrieval.

Applies deterministic intent routing to filter out irrelevant storage channels
and prevent I/O saturation on edge/desktop instances.

Enforces the explicit-scope invariance principle: when caller explicitly specifies
memory types, channel pruning is bypassed and only adaptive weighting is applied.

[INPUT]
- config: MemoryConfig
- query: str
- memory_types: list[MemoryType]
- memory_types_unspecified: bool

[OUTPUT]
- ChannelPruningResult: Resolved search types, adjusted config, and routing decision.

[POS]
Memory retrieval channel pruning and sub-graph dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.intent_recognizers import (
    DeterministicIntentRouter,
    IntentRoutingDecision,
    QueryIntentRecognizer,
)
from myrm_agent_harness.toolkits.memory.types import MemoryType


@dataclass(frozen=True, slots=True)
class ChannelPruningResult:
    """Outcome of channel pruning and routing.

    Attributes:
        search_types: Filtered memory types to execute against backing stores.
        runtime_config: MemoryConfig with adjusted type weights.
        decision: Full IntentRoutingDecision instance (or None if disabled).
        pruned_types: List of memory types safely omitted to conserve I/O.
    """

    search_types: list[MemoryType]
    runtime_config: MemoryConfig
    decision: IntentRoutingDecision | None
    pruned_types: list[MemoryType]


class ChannelPruner:
    """Deterministic channel pruner with explicit-scope protection."""

    DEFAULT_ROUTER: ClassVar[DeterministicIntentRouter] = DeterministicIntentRouter()

    @classmethod
    def resolve_channels(
        cls,
        config: MemoryConfig,
        query: str,
        memory_types: list[MemoryType],
        *,
        memory_types_unspecified: bool,
    ) -> ChannelPruningResult:
        """Resolve search channels based on intent and caller constraints.

        Args:
            config: Baseline memory configuration.
            query: User search query.
            memory_types: Initial memory types list.
            memory_types_unspecified: True if types defaulted because caller passed None.

        Returns:
            ChannelPruningResult with final types and adjusted config.
        """
        initial_search_types = [t for t in memory_types if t != MemoryType.CLAIM]

        if not config.retrieval.enable_intent_recognition:
            return ChannelPruningResult(
                search_types=initial_search_types,
                runtime_config=config,
                decision=None,
                pruned_types=[],
            )

        recognizer: QueryIntentRecognizer = (
            config.retrieval.intent_recognizer or cls.DEFAULT_ROUTER
        )
        decision = recognizer.recognize(query)

        # 1. Apply adaptive type weights if confidence is sufficient
        if decision.confidence > DeterministicIntentRouter.MODERATE_CONFIDENCE_THRESHOLD:
            adjusted_retrieval = replace(config.retrieval, type_weights=decision.type_weights)
            effective_config = replace(config, retrieval=adjusted_retrieval)
        else:
            effective_config = config

        # 2. Enforce Explicit-Scope Invariance:
        # If caller explicitly specified types, never prune channels!
        if not memory_types_unspecified:
            return ChannelPruningResult(
                search_types=initial_search_types,
                runtime_config=effective_config,
                decision=decision,
                pruned_types=[],
            )

        # 3. High-confidence deterministic pruning for auto-defaulted calls
        if (
            decision.confidence >= DeterministicIntentRouter.HIGH_CONFIDENCE_THRESHOLD
            and decision.target_types
        ):
            candidate_types = [t for t in decision.target_types if t in initial_search_types]
            if candidate_types:
                pruned = [t for t in initial_search_types if t not in candidate_types]
                return ChannelPruningResult(
                    search_types=candidate_types,
                    runtime_config=effective_config,
                    decision=decision,
                    pruned_types=pruned,
                )

        return ChannelPruningResult(
            search_types=initial_search_types,
            runtime_config=effective_config,
            decision=decision,
            pruned_types=[],
        )

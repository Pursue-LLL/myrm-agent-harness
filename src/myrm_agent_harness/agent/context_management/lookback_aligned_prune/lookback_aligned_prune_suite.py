"""Master facade suite for prompt cache lookback position aligned pruning floor.

[INPUT]
- lookback_prune_types: All contracts, enums, floor results, decisions, and configuration models.
- provider_block_projector: ProviderBlockProjector.
- lookback_floor_calculator: LookbackFloorCalculator.
- lookback_aligned_pruner: LookbackAlignedPruner.

[OUTPUT]
- PromptCacheLookbackPositionAlignedPruneFloorSuite: Master facade unifying
  emitted block projection, lookback floor boundary calculation, and cache-preserving prune gating.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.lookback_aligned_prune
- Module: lookback_aligned_prune_suite.py
"""

from typing import Mapping, Optional, Sequence

from myrm_agent_harness.agent.context_management.lookback_aligned_prune.lookback_aligned_pruner import (
    LookbackAlignedPruner,
)
from myrm_agent_harness.agent.context_management.lookback_aligned_prune.lookback_floor_calculator import (
    LookbackFloorCalculator,
)
from myrm_agent_harness.agent.context_management.lookback_aligned_prune.lookback_prune_types import (
    LookbackAlignedPruneConfig,
    LookbackFloorResult,
    LookbackPruneDecision,
    ProjectedContentBlock,
)
from myrm_agent_harness.agent.context_management.lookback_aligned_prune.provider_block_projector import (
    ProviderBlockProjector,
)


class PromptCacheLookbackPositionAlignedPruneFloorSuite:
    """Master facade providing lookback-aligned prune floor governance for prompt cache longevity."""

    def __init__(self, config: Optional[LookbackAlignedPruneConfig] = None) -> None:
        self._config = config or LookbackAlignedPruneConfig()
        self._projector = ProviderBlockProjector()
        self._floor_calculator = LookbackFloorCalculator(self._config)
        self._pruner = LookbackAlignedPruner(self._config)

    @property
    def projector(self) -> ProviderBlockProjector:
        """Access the provider content block projector."""
        return self._projector

    @property
    def floor_calculator(self) -> LookbackFloorCalculator:
        """Access the lookback floor boundary calculator."""
        return self._floor_calculator

    @property
    def pruner(self) -> LookbackAlignedPruner:
        """Access the cache-aligned candidate pruner."""
        return self._pruner

    def project_conversation_blocks(
        self,
        messages: Sequence[Mapping[str, str]],
    ) -> Sequence[ProjectedContentBlock]:
        """Projects conversation turns into discrete emitted content blocks."""
        return self._projector.project_messages(messages)

    def calculate_lookback_floor(
        self,
        projected_blocks: Sequence[ProjectedContentBlock],
        provider_name: str = "anthropic",
    ) -> LookbackFloorResult:
        """Computes the earliest content block and message index protected by prompt caching."""
        return self._floor_calculator.calculate_floor(
            projected_blocks=projected_blocks,
            provider_name=provider_name,
        )

    def evaluate_safe_prune_decisions(
        self,
        messages: Sequence[Mapping[str, str]],
        provider_name: str = "anthropic",
        token_budget: Optional[int] = None,
    ) -> Sequence[LookbackPruneDecision]:
        """Evaluates all candidate tool messages, preventing pruning inside the active lookback window."""
        projected = self._projector.project_messages(messages)
        floor = self._floor_calculator.calculate_floor(projected, provider_name=provider_name)
        return self._pruner.evaluate_pruning_candidates(
            projected_blocks=projected,
            floor_result=floor,
            target_token_budget=token_budget,
        )

    def is_message_in_cache_lookback_window(
        self,
        messages: Sequence[Mapping[str, str]],
        target_message_index: int,
        provider_name: str = "anthropic",
    ) -> bool:
        """Returns True if the specified message index resides within the protected cache window."""
        projected = self._projector.project_messages(messages)
        floor = self._floor_calculator.calculate_floor(projected, provider_name=provider_name)
        return target_message_index >= floor.protected_floor_message_index

"""Cache-preserving tool output pruner respecting lookback position floors.

[INPUT]
- lookback_prune_types: LookbackAlignedPruneConfig, LookbackFloorResult, LookbackPruneDecision,
  ProjectedContentBlock.

[OUTPUT]
- LookbackAlignedPruner: Evaluates candidate tool outputs for pruning, strictly prohibiting
  mutations within the active prompt cache lookback floor window.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.lookback_aligned_prune
- Module: lookback_aligned_pruner.py
"""

from typing import List, Optional, Sequence

from myrm_agent_harness.agent.context_management.lookback_aligned_prune.lookback_prune_types import (
    LookbackAlignedPruneConfig,
    LookbackFloorResult,
    LookbackPruneDecision,
    ProjectedContentBlock,
)


class LookbackAlignedPruner:
    """Safely evaluates pruning candidates while respecting immutable prompt cache boundaries."""

    def __init__(self, config: Optional[LookbackAlignedPruneConfig] = None) -> None:
        self._config = config or LookbackAlignedPruneConfig()

    def evaluate_pruning_candidates(
        self,
        projected_blocks: Sequence[ProjectedContentBlock],
        floor_result: LookbackFloorResult,
        target_token_budget: Optional[int] = None,
    ) -> Sequence[LookbackPruneDecision]:
        """Evaluates each prunable tool output against lookback boundaries and token limits.

        Args:
            projected_blocks: Content blocks projected from the conversation history.
            floor_result: Boundary result calculated by LookbackFloorCalculator.
            target_token_budget: Optional suffix token budget triggering pruning needs.

        Returns:
            Tuple of LookbackPruneDecision indicating which blocks can be safely pruned.
        """
        budget = target_token_budget or self._config.max_token_budget_for_suffix
        decisions: List[LookbackPruneDecision] = []

        # Group prunable blocks by message index
        prunable_blocks = [b for b in projected_blocks if b.is_prunable_tool_output]

        for block in prunable_blocks:
            msg_idx = block.message_index

            # Critical invariant: blocks inside or newer than the lookback floor are IMMUTABLE
            if msg_idx >= floor_result.protected_floor_message_index:
                decisions.append(
                    LookbackPruneDecision(
                        message_index=msg_idx,
                        can_prune=False,
                        is_protected_by_floor=True,
                        estimated_saved_tokens=0,
                        reason=(
                            f"Protected by prompt cache lookback floor "
                            f"(msg_index={msg_idx} >= floor={floor_result.protected_floor_message_index}). "
                            "Pruning forbidden to prevent cache rupture."
                        ),
                    )
                )
            else:
                # Outside active cache lookback window: safe to prune
                decisions.append(
                    LookbackPruneDecision(
                        message_index=msg_idx,
                        can_prune=True,
                        is_protected_by_floor=False,
                        estimated_saved_tokens=block.token_count,
                        reason=(
                            f"Outside prompt cache lookback floor "
                            f"(msg_index={msg_idx} < floor={floor_result.protected_floor_message_index}). "
                            f"Safe to prune ~{block.token_count} tokens."
                        ),
                    )
                )

        return tuple(decisions)

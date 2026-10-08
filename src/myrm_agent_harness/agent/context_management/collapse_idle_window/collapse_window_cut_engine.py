# [INPUT]: CollapseWindowConfig, CollapseWindowReceipt, IdleStreamCollapser, StepType, StreamStepItem
# [OUTPUT]: CollapseWindowCutEngine
# [POS]: agent/context_management/collapse_idle_window/collapse_window_cut_engine.py

"""Window cutting engine enforcing collapse-before-cut causal ordering on stream steps.

[INPUT]
- CollapseWindowConfig: Parameter settings for tail bound, window size, and pruning.
- CollapseWindowReceipt: Verifiable audit receipt summarizing transformation metrics.
- IdleStreamCollapser: Sub-engine collapsing consecutive idle runs and pruning noise.
- StepType: Event step classification.
- StreamStepItem: Stream event model.

[OUTPUT]
- CollapseWindowCutEngine: Engine enforcing collapse-before-cut sequencing to protect tail history.

[POS]
Pipeline engine coordinating raw bounding, noise pruning, run collapsing, and window cut.
"""

from __future__ import annotations

from typing import Sequence
import uuid

from .collapse_idle_types import (
    CollapseWindowConfig,
    CollapseWindowReceipt,
    StepType,
    StreamStepItem,
)
from .idle_stream_collapser import IdleStreamCollapser


class CollapseWindowCutEngine:
    """Enforces causal sequencing: Raw Bound -> Prune -> Collapse Idles -> Cut Window."""

    def __init__(self, config: CollapseWindowConfig) -> None:
        self._config = config
        self._collapser = IdleStreamCollapser(config)

    def process_stream(
        self,
        steps: Sequence[StreamStepItem],
    ) -> tuple[tuple[StreamStepItem, ...], CollapseWindowReceipt]:
        """Transform stream through the strictly ordered collapse-before-cut pipeline."""
        raw_count = len(steps)
        if raw_count == 0:
            receipt = CollapseWindowReceipt.create(
                receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
                raw_step_count=0,
                pruned_step_count=0,
                collapsed_idle_count=0,
                effective_count_before_cut=0,
                final_window_count=0,
                tail_actions_preserved_count=0,
            )
            return (), receipt

        # Step 1: Raw Tail Bounding (guard against unbounded memory expansion)
        bounded_steps = tuple(steps[-self._config.raw_tail_bound :])

        # Step 2: Redundant Step & Ephemeral Noise Pruning
        pruned_steps, pruned_count = self._collapser.prune_redundant_stream(bounded_steps)

        # Step 3: Consecutive Idle & Error Run Collapsing (BEFORE window cut)
        collapsed_steps, collapsed_count = self._collapser.collapse_consecutive_runs(pruned_steps)
        effective_before_cut = len(collapsed_steps)

        # Step 4: Window Cut AFTER Collapsing
        # Cutting AFTER collapsing guarantees that 20 consecutive idle steps only take 1 window slot,
        # preserving the crucial preceding actions without premature eviction.
        final_window = tuple(collapsed_steps[-self._config.target_window_size :])
        final_count = len(final_window)

        # Count preserved historical actions in the final window
        tail_actions_preserved = sum(
            1 for item in final_window if item.step_type == StepType.ACTION
        )

        receipt = CollapseWindowReceipt.create(
            receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
            raw_step_count=raw_count,
            pruned_step_count=pruned_count,
            collapsed_idle_count=collapsed_count,
            effective_count_before_cut=effective_before_cut,
            final_window_count=final_count,
            tail_actions_preserved_count=tail_actions_preserved,
        )

        return final_window, receipt

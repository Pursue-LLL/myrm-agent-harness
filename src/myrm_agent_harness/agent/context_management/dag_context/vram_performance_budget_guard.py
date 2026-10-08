"""VRAM hardware-aware performance budget guard locking active prompt to 6K-8K safety watermarks.

[INPUT]
- DagContextBudgetConfig, TurnRecord, HierarchicalDagNode: Domain models.

[OUTPUT]
- VramBudgetEvaluation: Telemetry assessment of prompt token budget saturation.
- VramPerformanceBudgetGuard: Enforces local GPU memory safety preventing TTFT degradation and KV cache OOM.

[POS]
Hardware resource guard layer in DAG context subsystem protecting local consumer GPU inference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .dag_types import DagContextBudgetConfig, HierarchicalDagNode, TurnRecord


@dataclass(frozen=True)
class VramBudgetEvaluation:
    """Evaluation metrics representing active prompt size relative to GPU hardware budgets."""

    total_active_tokens: int
    target_budget_tokens: int
    saturation_ratio: float
    is_budget_exceeded: bool
    recommended_action: str


class VramPerformanceBudgetGuard:
    """Monitors and constrains active prompt volume to ensure predictable TTFT and KV cache footprint."""

    def __init__(self, config: DagContextBudgetConfig | None = None) -> None:
        self._config = config or DagContextBudgetConfig()

    def evaluate_active_prompt(
        self,
        active_turns: Sequence[TurnRecord],
        active_pages: Sequence[HierarchicalDagNode],
        root_skeleton: HierarchicalDagNode | None = None,
        base_prompt_tokens: int = 1000,
    ) -> VramBudgetEvaluation:
        """Evaluate token usage of active context against hardware-safe VRAM performance ceilings."""
        turns_tokens = sum(t.token_estimate or len(t.content.split()) for t in active_turns)
        pages_tokens = sum(p.token_count for p in active_pages)
        root_tokens = root_skeleton.token_count if root_skeleton else 0

        total_tokens = base_prompt_tokens + turns_tokens + pages_tokens + root_tokens
        budget = self._config.target_prompt_token_budget
        saturation = round(total_tokens / max(1, budget), 3)
        exceeded = total_tokens > budget

        if not self._config.vram_budget_lock:
            action = "budget_lock_disabled"
        elif exceeded:
            action = "fold_older_turns_to_pages"
        elif saturation > 0.8:
            action = "nearing_vram_safety_ceiling"
        else:
            action = "healthy_within_vram_budget"

        return VramBudgetEvaluation(
            total_active_tokens=total_tokens,
            target_budget_tokens=budget,
            saturation_ratio=saturation,
            is_budget_exceeded=exceeded,
            recommended_action=action,
        )

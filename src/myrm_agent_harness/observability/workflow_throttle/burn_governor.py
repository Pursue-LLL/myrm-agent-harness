"""
[INPUT]: Workflow token metrics stream and budget ceiling configurations.
[OUTPUT]: Smoothed burn rate calculations and tiered budget safety verdicts.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/workflow_throttle/burn_governor.py
"""

from collections import deque
import time
from typing import Deque, Dict, List, Optional, Tuple

from .models import (
    BudgetLadderTier,
    BudgetLadderVerdict,
    WorkflowTokenBurnSample,
)


class WorkflowTokenBurnGovernor:
    """
    Monitors instantaneous token burn rates across massive workflow executions
    and enforces tiered budget safety protections.
    """

    def __init__(self, window_size: int = 10) -> None:
        self._window_size = window_size
        # Map of workflow_id -> sliding history of (timestamp, cumulative_tokens, cumulative_cost)
        self._history: Dict[str, Deque[Tuple[float, int, float]]] = {}

    def record_checkpoint(
        self,
        workflow_id: str,
        cumulative_tokens: int,
        cumulative_cost_usd: float,
        timestamp: Optional[float] = None,
    ) -> Tuple[float, float]:
        """
        Records a progress point and calculates smoothed (tokens_per_sec, cost_per_hour_usd).
        """
        now = timestamp if timestamp is not None else time.time()
        if workflow_id not in self._history:
            self._history[workflow_id] = deque(maxlen=self._window_size)

        queue = self._history[workflow_id]
        queue.append((now, cumulative_tokens, cumulative_cost_usd))

        if len(queue) < 2:
            return 0.0, 0.0

        oldest_time, oldest_tokens, oldest_cost = queue[0]
        dt = now - oldest_time
        if dt <= 0.001:
            return 0.0, 0.0

        d_tokens = max(0, cumulative_tokens - oldest_tokens)
        d_cost = max(0.0, cumulative_cost_usd - oldest_cost)

        tokens_per_sec = d_tokens / dt
        # Hourly cost projection = cost/sec * 3600
        cost_per_hour_usd = (d_cost / dt) * 3600.0

        return tokens_per_sec, cost_per_hour_usd

    def evaluate_budget(
        self,
        workflow_id: str,
        cumulative_tokens: int,
        budget_tokens: Optional[int] = None,
        cumulative_cost_usd: float = 0.0,
        budget_cost_usd: Optional[float] = None,
    ) -> BudgetLadderVerdict:
        """
        Evaluates current workflow metrics against tiered safety limits.
        Triggers soft notices at 50%, adaptive throttle/degradation at 80%,
        and safe freeze at 100%.
        """
        used_percentages: List[float] = []

        if budget_tokens is not None and budget_tokens > 0:
            used_percentages.append((cumulative_tokens / budget_tokens) * 100.0)

        if budget_cost_usd is not None and budget_cost_usd > 0.0:
            used_percentages.append((cumulative_cost_usd / budget_cost_usd) * 100.0)

        used_pct = max(used_percentages) if used_percentages else 0.0

        if used_pct >= 100.0:
            return BudgetLadderVerdict(
                workflow_id=workflow_id,
                tier=BudgetLadderTier.TIER3_SUSPENDED,
                used_pct=used_pct,
                is_throttled=True,
                is_suspended=True,
                throttle_factor=0.0,
                action_message=f"已达预设预算上限（{used_pct:.1f}%），执行流已触发安全挂起保护，防止进一步透支",
                recommended_model_tier="halted",
            )
        elif used_pct >= 80.0:
            return BudgetLadderVerdict(
                workflow_id=workflow_id,
                tier=BudgetLadderTier.TIER2_DEGRADED,
                used_pct=used_pct,
                is_throttled=True,
                is_suspended=False,
                throttle_factor=0.5,
                action_message=f"预算消耗已达 {used_pct:.1f}%，触发阶梯二自适应限流降级，后续非关键任务建议采用经济模型",
                recommended_model_tier="economy",
            )
        elif used_pct >= 50.0:
            return BudgetLadderVerdict(
                workflow_id=workflow_id,
                tier=BudgetLadderTier.TIER1_NOTICE,
                used_pct=used_pct,
                is_throttled=False,
                is_suspended=False,
                throttle_factor=1.0,
                action_message=f"预算消耗达 {used_pct:.1f}%，处于阶段一平稳关注水位，当前速率符合预期",
                recommended_model_tier="primary",
            )
        else:
            return BudgetLadderVerdict(
                workflow_id=workflow_id,
                tier=BudgetLadderTier.NORMAL,
                used_pct=used_pct,
                is_throttled=False,
                is_suspended=False,
                throttle_factor=1.0,
                action_message="预算水位充裕（<50%），全速无阻塞并发执行中",
                recommended_model_tier="primary",
            )

"""Bounded step budget for segment execution.

A segment run may only take a bounded number of steps before it must yield so the
checkpoint can settle and another segment can claim the job; this budget is the
counter that enforces that contract.

[INPUT]
- (none — pure counter)

[OUTPUT]
- StepBudgetExceededError: 步数超出预算
- BoundedSegmentBudget: 当前步数、剩余步数与步进校验

[POS]
Step-budget side of bounded segment execution, consumed by the job supervisor.
"""

from __future__ import annotations


class StepBudgetExceededError(Exception):
    """切片步数超出预算时抛出，驱动切片让渡与断点沉淀。"""


class BoundedSegmentBudget:
    """切片步数预算计量器。"""

    def __init__(self, max_steps: int = 20) -> None:
        self._max_steps = max_steps
        self._current_step = 0

    @property
    def current_step(self) -> int:
        """获取当前已执行步数。"""
        return self._current_step

    @property
    def remaining_steps(self) -> int:
        """获取剩余可用步数。"""
        return max(0, self._max_steps - self._current_step)

    def advance_step(self) -> None:
        """步进一次计算，超出预算时抛出异常。"""
        if self._current_step >= self._max_steps:
            raise StepBudgetExceededError(f"Step budget of {self._max_steps} exceeded at step {self._current_step + 1}")
        self._current_step += 1

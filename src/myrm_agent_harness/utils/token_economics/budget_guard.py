"""Protocol-based budget control for LLM cost management.

[INPUT]

[OUTPUT]
- BudgetStatus: 预算状态枚举（OK, WARNING, FINALIZATION, EXCEEDED）
- BudgetChecker: 预算检查协议
- DailyBudgetGuard: 简单日预算实现

[POS]
Budget guard (framework layer). Provides protocol definition and simple implementation; business layer can extend.

"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from enum import StrEnum
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class BudgetStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    FINALIZATION = "finalization"
    EXCEEDED = "exceeded"


@runtime_checkable
class BudgetChecker(Protocol):
    """预算检查协议。业务层可实现更复杂的策略（月预算、按用户等）。"""

    def check_budget(self, cost: float) -> BudgetStatus:
        """检查预算状态（不修改状态）。"""
        ...

    def record_cost(self, cost: float) -> BudgetStatus:
        """记录成本并返回新的预算状态。"""
        ...

    def get_remaining_budget(self) -> float | None:
        """获取剩余预算（USD），None 表示无限制。"""
        ...


class DailyBudgetGuard:
    """简单日预算守卫。

    日期变更时自动重置累计成本。
    WARNING 在达到 warning_threshold 时触发。
    EXCEEDED 在超过 daily_budget_usd 时触发。

    框架层不阻断 LLM 调用，只提供信号和可选回调。
    """

    def __init__(
        self,
        daily_budget_usd: float,
        warning_threshold: float = 0.8,
        on_warning: Callable[[float, float], None] | None = None,
        on_exceeded: Callable[[float, float], None] | None = None,
        initial_cost: float = 0.0,
    ) -> None:
        """
        Args:
            daily_budget_usd: 日预算上限（USD）
            warning_threshold: 预警阈值（0-1），默认 80%
            on_warning: 预警回调 (today_cost, budget)
            on_exceeded: 超限回调 (today_cost, budget)
            initial_cost: 已累计花费（用于策略刷新或进程恢复时继承历史花费）
        """
        self._daily_budget_usd = daily_budget_usd
        self._warning_threshold = warning_threshold
        self._on_warning = on_warning
        self._on_exceeded = on_exceeded
        self._today_cost: float = initial_cost
        self._current_date: date = date.today()

    def _maybe_reset_day(self) -> None:
        today = date.today()
        if today != self._current_date:
            logger.info(
                "Budget day reset: %s -> %s (yesterday cost: $%.4f)",
                self._current_date,
                today,
                self._today_cost,
            )
            self._today_cost = 0.0
            self._current_date = today

    def check_budget(self, cost: float = 0.0) -> BudgetStatus:
        self._maybe_reset_day()
        projected = self._today_cost + cost
        if projected >= self._daily_budget_usd:
            return BudgetStatus.EXCEEDED
        if projected >= self._daily_budget_usd * self._warning_threshold:
            return BudgetStatus.WARNING
        return BudgetStatus.OK

    def record_cost(self, cost: float) -> BudgetStatus:
        """记录成本并返回新的预算状态。触发回调（如果配置了）。"""
        self._maybe_reset_day()
        self._today_cost += cost

        if self._today_cost >= self._daily_budget_usd:
            logger.warning(
                "Daily budget EXCEEDED: $%.4f / $%.2f",
                self._today_cost,
                self._daily_budget_usd,
            )
            if self._on_exceeded:
                self._on_exceeded(self._today_cost, self._daily_budget_usd)
            return BudgetStatus.EXCEEDED

        if self._today_cost >= self._daily_budget_usd * self._warning_threshold:
            logger.warning(
                "Daily budget WARNING: $%.4f / $%.2f (%.0f%%)",
                self._today_cost,
                self._daily_budget_usd,
                (self._today_cost / self._daily_budget_usd) * 100,
            )
            if self._on_warning:
                self._on_warning(self._today_cost, self._daily_budget_usd)
            return BudgetStatus.WARNING

        return BudgetStatus.OK

    def get_remaining_budget(self) -> float | None:
        self._maybe_reset_day()
        return max(0.0, self._daily_budget_usd - self._today_cost)

    @property
    def today_cost(self) -> float:
        self._maybe_reset_day()
        return self._today_cost

    @property
    def daily_budget_usd(self) -> float:
        return self._daily_budget_usd

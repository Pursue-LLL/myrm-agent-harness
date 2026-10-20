"""Cron 任务与不可摧毁作业系统桥接适配器。

将 toolkits/cron 的执行与重试策略统一交由 Job System 托管，
消除 Cron 孤岛式盲目重试风险，实现副作用感知与求证对账对齐。

[INPUT]
- __future__
- dataclasses
- enum
- typing

[OUTPUT]
- CronExecutionDecision
- CronJobEvaluationResult
- CronJobAdapter

[POS]
Cron 任务与不可摧毁作业系统桥接适配器。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CronExecutionDecision(str, Enum):
    """Cron 任务调度与对账裁决枚举。"""

    SUCCESS = "SUCCESS"
    RETRY_SAFE = "RETRY_SAFE"
    BLOCK_UNCERTAIN_SIDE_EFFECT = "BLOCK_UNCERTAIN_SIDE_EFFECT"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"


@dataclass(frozen=True)
class CronJobEvaluationResult:
    """Cron 评估决策结果。"""

    decision: CronExecutionDecision
    reason: str
    can_retry_immediately: bool = False
    requires_approval: bool = False


class CronJobAdapter:
    """Cron 统一作业适配器。"""

    def __init__(self, max_consecutive_failures: int = 3) -> None:
        self._max_consecutive_failures = max_consecutive_failures

    def evaluate_execution(
        self,
        exit_code: int,
        has_side_effect: bool,
        external_message_id: Optional[str] = None,
        consecutive_failures: int = 0,
    ) -> CronJobEvaluationResult:
        """评估 Cron 执行结果并给出作业系统对齐处置决策。"""
        # 退出码为 0 代表正常执行完成
        if exit_code == 0:
            return CronJobEvaluationResult(
                decision=CronExecutionDecision.SUCCESS,
                reason="Task completed successfully with exit code 0",
            )

        # 存在副作用，但有外部消息确认凭证时，视为部分成功并对账
        if has_side_effect and external_message_id is not None:
            return CronJobEvaluationResult(
                decision=CronExecutionDecision.SUCCESS,
                reason=f"External message confirmation received: {external_message_id}",
            )

        # 存在副作用且无外部求证凭据，严禁盲目重试，必须阻断
        if has_side_effect:
            return CronJobEvaluationResult(
                decision=CronExecutionDecision.BLOCK_UNCERTAIN_SIDE_EFFECT,
                reason="Non-idempotent side effect detected without confirmation; paused for approval",
                requires_approval=True,
            )

        # 纯计算/无副作用任务：检查是否超出重试次数预算
        if consecutive_failures >= self._max_consecutive_failures:
            return CronJobEvaluationResult(
                decision=CronExecutionDecision.TERMINAL_FAILURE,
                reason=f"Exceeded max failure threshold of {self._max_consecutive_failures}",
            )

        # 安全重试
        return CronJobEvaluationResult(
            decision=CronExecutionDecision.RETRY_SAFE,
            reason="Idempotent task failed safely; scheduled for retry",
            can_retry_immediately=True,
        )

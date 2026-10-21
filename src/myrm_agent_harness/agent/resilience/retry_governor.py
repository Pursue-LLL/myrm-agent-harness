"""工业级弹性重试调度治理器模块。

聚合强类型失败原因分类器与同会话就地三明治压缩器，
依据确定性优先级提供精准的三态自适应重试裁决（熔断、退避重试、同会话就地压缩再重发），
彻底消灭 401/402 盲目死循环重试与上下文溢出逃逸新建空白会话的系统缺陷。

[INPUT]
- __future__
- logging
- random
- dataclasses

[OUTPUT]
- logger
- RetryDirective
- ResilientRetryGovernor

[POS]
工业级弹性重试调度治理器模块。
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from myrm_agent_harness.agent.resilience.failure_reasons import (
    FailureAssessment,
    RetryDisposition,
    TypedFailureClassifier,
    TypedFailureReason,
)
from myrm_agent_harness.agent.resilience.in_session_compactor import (
    CompactionResult,
    InSessionTrajectoryCompactor,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetryDirective:
    """重试治理调度执行指令实体。"""

    should_retry: bool
    disposition: RetryDisposition
    reason: TypedFailureReason
    backoff_seconds: float
    user_guidance: str
    compacted_context: dict[str, object] | None = None
    compaction_meta: CompactionResult | None = None


class ResilientRetryGovernor:
    """弹性重试调度治理器。"""

    def __init__(
        self,
        *,
        max_retries: int = 3,
        base_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 30.0,
        enable_jitter: bool = True,
    ) -> None:
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._enable_jitter = enable_jitter

    def compute_backoff(self, attempt: int) -> float:
        """计算带抖动的指数退避延迟秒数。"""
        # attempt 从 1 开始
        exponent = max(0, attempt - 1)
        raw_backoff = self._base_backoff * (2.0**exponent)
        clamped = min(self._max_backoff, raw_backoff)
        if self._enable_jitter:
            jitter = random.uniform(0.0, 0.5 * self._base_backoff)
            return round(clamped + jitter, 3)
        return round(clamped, 3)

    def evaluate(
        self,
        error: Exception | str,
        *,
        attempt: int = 1,
        http_status: int | None = None,
        context: dict[str, object] | None = None,
    ) -> RetryDirective:
        """评估异常并给出权威重试指令。

        参数:
            error: 异常实例或原始错误信息
            attempt: 当前失败的尝试次数（1-based）
            http_status: 可选的 HTTP 状态码
            context: 当前会话的上下文字典（可包含 session_id, messages 等）
        """
        assessment: FailureAssessment = TypedFailureClassifier.classify(
            error,
            http_status=http_status,
        )

        # 1. 致命或不可恢复错误（鉴权/欠费/配置缺失/模型不存在） -> 坚决立即熔断
        if assessment.disposition == RetryDisposition.RETRY_NONE:
            logger.warning(
                "Immediate circuit break for %s: %s (no retry allowed)",
                assessment.reason.value,
                assessment.user_message,
            )
            return RetryDirective(
                should_retry=False,
                disposition=RetryDisposition.RETRY_NONE,
                reason=assessment.reason,
                backoff_seconds=0.0,
                user_guidance=f"{assessment.user_message} 建议操作: {assessment.suggested_action}",
                compacted_context=None,
                compaction_meta=None,
            )

        # 2. 上下文溢出错误 -> 触发同会话就地三明治压缩并原地重发（NEVER mint fresh session）
        if assessment.disposition == RetryDisposition.RETRY_COMPRESS_THEN_RESUME:
            if attempt > self._max_retries:
                logger.error(
                    "Context overflow retry budget exhausted after %d attempts",
                    attempt,
                )
                return RetryDirective(
                    should_retry=False,
                    disposition=RetryDisposition.RETRY_COMPRESS_THEN_RESUME,
                    reason=assessment.reason,
                    backoff_seconds=0.0,
                    user_guidance="上下文就地压缩重试预算已耗尽，请精简本次任务要求后重试。",
                    compacted_context=None,
                    compaction_meta=None,
                )

            # 执行就地压缩
            session_id = "unknown_session"
            messages: list[dict[str, str]] = []
            if context is not None:
                session_id = str(context.get("session_id", "default_session"))
                raw_msgs = context.get("messages")
                if isinstance(raw_msgs, list):
                    for item in raw_msgs:
                        if isinstance(item, dict):
                            messages.append({str(k): str(v) for k, v in item.items()})

            compaction = InSessionTrajectoryCompactor.compact(session_id, messages)
            new_context = dict(context) if context is not None else {}
            new_context["session_id"] = session_id  # 严格保持原 session_id
            new_context["messages"] = compaction.compacted_messages
            new_context["_in_session_compacted"] = True

            logger.info(
                "In-session compaction succeeded for session '%s': %d -> %d messages (ratio %.2f)",
                session_id,
                compaction.original_message_count,
                compaction.compacted_message_count,
                compaction.compression_ratio,
            )

            return RetryDirective(
                should_retry=True,
                disposition=RetryDisposition.RETRY_COMPRESS_THEN_RESUME,
                reason=assessment.reason,
                backoff_seconds=0.5,  # 压缩后轻微停顿即可立刻重发
                user_guidance="检测到上下文已满，已在同会话内就地精简历史并继续攻坚。",
                compacted_context=new_context,
                compaction_meta=compaction,
            )

        # 3. 瞬态错误（限流/5xx服务端错误/超时） -> 同会话抖动指数退避重试
        if attempt >= self._max_retries:
            logger.warning(
                "Transient retry budget exhausted for %s after %d attempts",
                assessment.reason.value,
                attempt,
            )
            return RetryDirective(
                should_retry=False,
                disposition=RetryDisposition.RETRY_RESUME,
                reason=assessment.reason,
                backoff_seconds=0.0,
                user_guidance=f"{assessment.user_message}（已达到最大重试上限 {self._max_retries} 次）",
                compacted_context=None,
                compaction_meta=None,
            )

        backoff = self.compute_backoff(attempt)
        logger.info(
            "Scheduling transient retry (%d/%d) for %s in %.2fs",
            attempt,
            self._max_retries,
            assessment.reason.value,
            backoff,
        )
        return RetryDirective(
            should_retry=True,
            disposition=RetryDisposition.RETRY_RESUME,
            reason=assessment.reason,
            backoff_seconds=backoff,
            user_guidance=assessment.user_message,
            compacted_context=context,
            compaction_meta=None,
        )

"""闭集强类型失败原因分级裁决与三态重试决策枚举模块。

定义 13 个工业级机器可读失败原因码与严格确定性匹配优先级，
杜绝 401/402 鉴权与欠费错误盲目死循环重试，为运行时提供确定的自愈与熔断分级裁决。

[INPUT]
- __future__
- re
- dataclasses
- enum

[OUTPUT]
- TypedFailureReason
- RetryDisposition
- FailureAssessment
- TypedFailureClassifier

[POS]
闭集强类型失败原因分级裁决与三态重试决策枚举模块。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class TypedFailureReason(StrEnum):
    """闭集标准机器可读失败原因码枚举。"""

    # 平台与传输层
    RUNTIME_OFFLINE = "runtime_offline"
    QUEUED_EXPIRED = "queued_expired"
    DELIVERY_TIMEOUT = "delivery_timeout"
    AGENT_BLOCKED = "agent_blocked"
    CANCELLED = "cancelled"

    # 模型提供商与推理层
    PROVIDER_AUTH_OR_ACCESS = "provider_auth_or_access"
    PROVIDER_QUOTA_LIMIT = "provider_quota_limit"
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_SERVER_ERROR = "provider_server_error"
    CONTEXT_OVERFLOW = "context_overflow"
    MISSING_CONFIG = "missing_config"
    MODEL_UNAVAILABLE = "model_unavailable"
    UNKNOWN = "unknown"


class RetryDisposition(StrEnum):
    """三态自适应重试决策意图枚举。"""

    RETRY_NONE = "retry_none"  # 不可重试致命错误（鉴权/欠费/配置缺失），立即熔断
    RETRY_RESUME = "retry_resume"  # 瞬态错误（限流/服务超载/网络超时），同会话指数退避重试
    RETRY_COMPRESS_THEN_RESUME = "retry_compress_then_resume"  # 上下文超限，同会话就地压缩再重试（绝不新建会话）


@dataclass(frozen=True, slots=True)
class FailureAssessment:
    """失败评估诊断与重试决策不可变实体。"""

    reason: TypedFailureReason
    disposition: RetryDisposition
    user_message: str
    can_retry: bool
    http_status: int | None = None
    suggested_action: str | None = None


# 正则特征：高危与分类特征
_AUTH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:invalid_api_key|incorrect api key|authentication|unauthorized)\b", re.I),
    re.compile(r"\b(?:invalid api key|api key not found|permission_denied|forbidden)\b", re.I),
)

_QUOTA_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:insufficient_quota|quota_exceeded|out of credits?|billing|payment_required)\b", re.I),
    re.compile(r"\b(?:exceeded your current quota|account deactivated|balance)\b", re.I),
)

_RATE_LIMIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:rate_limit_exceeded|rate limit|too many requests|tokens per min|tpm|rpm)\b", re.I),
)

_CONTEXT_OVERFLOW_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:context_length_exceeded|maximum context length|prompt is too long|too many tokens)\b", re.I),
    re.compile(r"\b(?:context_overflow|reduce the length of the messages|token limit)\b", re.I),
)

_SERVER_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:bad_gateway|service_unavailable|gateway_timeout|internal_server_error)\b", re.I),
    re.compile(r"\b(?:overloaded|server error|502|503|504)\b", re.I),
)


class TypedFailureClassifier:
    """强类型确定性失败原因分类器。"""

    @classmethod
    def classify(
        cls,
        error: Exception | str,
        http_status: int | None = None,
    ) -> FailureAssessment:
        """依严格优先级裁决错误原因与重试意图。

        优先级规则：AUTH > QUOTA > RATE_LIMIT > SERVER_ERROR > CONTEXT_OVERFLOW > MISSING_CONFIG > MODEL_UNAVAILABLE > UNKNOWN
        """
        raw_msg = str(error).strip()
        status = http_status

        # 尝试从常见 LLM 异常中探测 status_code
        if status is None and hasattr(error, "status_code"):
            try:
                status = int(error.status_code)
            except (ValueError, TypeError):
                status = None

        # 1. 严格优先级 1: 认证与鉴权错误 (AUTH)
        # 核心防护：Anthropic 401 常见 "invalid, blocked or out of funds" 字样，若无优先级会误判为 quota！
        # 故只要 http_status == 401，或者匹配 AUTH 正则，强制确立为 AUTH！
        if status == 401 or any(p.search(raw_msg) for p in _AUTH_PATTERNS):
            return FailureAssessment(
                reason=TypedFailureReason.PROVIDER_AUTH_OR_ACCESS,
                disposition=RetryDisposition.RETRY_NONE,
                user_message="模型提供商身份鉴权失败（API Key 无效、已过期或无权访问指定模型）。",
                can_retry=False,
                http_status=status or 401,
                suggested_action="请检查并重新配置您的模型 API Key。",
            )

        # 2. 严格优先级 2: 账户额度与欠费 (QUOTA / BILLING)
        if status == 402 or any(p.search(raw_msg) for p in _QUOTA_PATTERNS):
            return FailureAssessment(
                reason=TypedFailureReason.PROVIDER_QUOTA_LIMIT,
                disposition=RetryDisposition.RETRY_NONE,
                user_message="模型提供商账户额度已耗尽或发生欠费。",
                can_retry=False,
                http_status=status or 402,
                suggested_action="请前往提供商控制台为账户充值或调整配额上限。",
            )

        # 3. 严格优先级 3: 瞬态限流 (RATE_LIMIT)
        if status == 429 or any(p.search(raw_msg) for p in _RATE_LIMIT_PATTERNS):
            return FailureAssessment(
                reason=TypedFailureReason.PROVIDER_RATE_LIMIT,
                disposition=RetryDisposition.RETRY_RESUME,
                user_message="触发模型提供商速率限制（TPM/RPM 超限），系统正在为您自动退避重试。",
                can_retry=True,
                http_status=status or 429,
                suggested_action="等待瞬态限流窗口恢复，正在原地重试。",
            )

        # 4. 严格优先级 4: 上下文溢出 (CONTEXT_OVERFLOW) -> 触发就地压缩，绝不新建会话
        if any(p.search(raw_msg) for p in _CONTEXT_OVERFLOW_PATTERNS):
            return FailureAssessment(
                reason=TypedFailureReason.CONTEXT_OVERFLOW,
                disposition=RetryDisposition.RETRY_COMPRESS_THEN_RESUME,
                user_message="对话轨迹超出模型最大上下文长度，正在为您就地压缩历史并原地继续攻坚。",
                can_retry=True,
                http_status=status or 400,
                suggested_action="同会话就地压缩上下文轨迹后原地重新推理。",
            )

        # 5. 严格优先级 5: 服务端故障与瞬态网络 (SERVER_ERROR / TIMEOUT)
        if (status is not None and 500 <= status <= 599) or any(p.search(raw_msg) for p in _SERVER_ERROR_PATTERNS):
            return FailureAssessment(
                reason=TypedFailureReason.PROVIDER_SERVER_ERROR,
                disposition=RetryDisposition.RETRY_RESUME,
                user_message="模型提供商服务端发生瞬态过载或内部错误，系统正在为您自动重试。",
                can_retry=True,
                http_status=status or 503,
                suggested_action="等待服务端恢复，正在原地退避重试。",
            )

        # 6. 严格优先级 6: 模型不存在或已下线 (MODEL_UNAVAILABLE)
        if status == 404 or "model_not_found" in raw_msg.lower():
            return FailureAssessment(
                reason=TypedFailureReason.MODEL_UNAVAILABLE,
                disposition=RetryDisposition.RETRY_NONE,
                user_message="指定的模型不存在、已下线或当前不可用。",
                can_retry=False,
                http_status=status or 404,
                suggested_action="请切换为其他可用的模型后重试。",
            )

        # 7. 严格优先级 7: 配置缺失 (MISSING_CONFIG)
        if "missing_config" in raw_msg.lower() or "not configured" in raw_msg.lower():
            return FailureAssessment(
                reason=TypedFailureReason.MISSING_CONFIG,
                disposition=RetryDisposition.RETRY_NONE,
                user_message="智能体缺少必要的模型配置或环境参数。",
                can_retry=False,
                http_status=None,
                suggested_action="请完善模型设置与环境变量配置。",
            )

        # 8. 默认兜底: 未知异常 (UNKNOWN)
        return FailureAssessment(
            reason=TypedFailureReason.UNKNOWN,
            disposition=RetryDisposition.RETRY_NONE,
            user_message=f"遇到未归类的运行时错误: {raw_msg[:120]}",
            can_retry=False,
            http_status=status,
            suggested_action="请查看系统日志以获取进一步排查信息。",
        )

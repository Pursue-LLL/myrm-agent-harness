"""[INPUT]
- typing (Standard library types)

[OUTPUT]
- ProviderErrorCategory: 模型提供方错误分类 (QUOTA_EXHAUSTED, RATE_LIMITED, AUTH_INVALID, OVERLOADED, UNKNOWN)
- ProviderQuotaClassification: 归因判定结果契约
- classify_provider_error: 将 HTTP 状态码与响应体解析为精准归因与排障行动建议

[POS]
myrm_agent_harness.observability.diagnostics.fleet_telemetry.provider_quota — 模型提供商配额耗尽与异常精准归因器。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum


class ProviderErrorCategory(StrEnum):
    """模型上游错误分类。"""

    QUOTA_EXHAUSTED = "quota_exhausted"  # 账户欠费、免费额度耗尽或计费被暂停
    RATE_LIMITED = "rate_limited"  # 触发 TPM / RPM / 并发限制
    AUTH_INVALID = "auth_invalid"  # API 密钥错误、已失效或权限不足
    OVERLOADED = "overloaded"  # 提供方服务暂时不可用或集群过载
    UNKNOWN = "unknown"  # 未知或其他异常


@dataclass(frozen=True, slots=True)
class ProviderQuotaClassification:
    """模型异常归因结果。"""

    is_provider_issue: bool
    category: ProviderErrorCategory
    root_cause: str
    recommended_action: str
    provider_name: str | None = None
    model_name: str | None = None


# 常见欠费与额度耗尽的特征关键词
_QUOTA_KEYWORDS: frozenset[str] = frozenset(
    [
        "insufficient_quota",
        "quota_exceeded",
        "credit_balance_too_low",
        "exceeded your current quota",
        "billing",
        "purchase more credits",
        "out of credits",
        "quota exceeded",
        "insufficient balance",
        "balance is not enough",
        "arrears",
        "credit issue",
    ]
)

# 常见限流特征关键词
_RATE_LIMIT_KEYWORDS: frozenset[str] = frozenset(
    [
        "rate_limit",
        "rate limit exceeded",
        "too many requests",
        "requests per minute",
        "tokens per minute",
        "tpm limit",
        "rpm limit",
        "concurrency limit",
    ]
)

# 常见鉴权失效关键词
_AUTH_KEYWORDS: frozenset[str] = frozenset(
    [
        "invalid_api_key",
        "incorrect api key",
        "unauthorized",
        "authentication failed",
        "invalid auth",
        "permission_denied",
        "api key not found",
    ]
)


def classify_provider_error(
    status_code: int,
    error_payload: str | dict[str, object] | None = None,
    *,
    provider_name: str | None = None,
    model_name: str | None = None,
) -> ProviderQuotaClassification:
    """分析大模型提供方返回的 HTTP 状态码与响应内容，精准识别是否为余额欠费或限流。

    Args:
        status_code: HTTP 响应状态码 (如 402, 429, 401, 503 等)
        error_payload: 响应体字符串或字典
        provider_name: 可选模型供应商名称 (如 anthropic, openai, deepseek)
        model_name: 可选模型名称

    Returns:
        ProviderQuotaClassification 结构化归因对象
    """
    raw_text = ""
    if isinstance(error_payload, dict):
        raw_text = json.dumps(error_payload).lower()
    elif isinstance(error_payload, str):
        raw_text = error_payload.lower()

    # 1. 显式 402 Payment Required 或命中配额耗尽特征词
    if status_code == 402 or any(kw in raw_text for kw in _QUOTA_KEYWORDS):
        provider_label = f"「{provider_name}」" if provider_name else "上游模型服务商"
        return ProviderQuotaClassification(
            is_provider_issue=True,
            category=ProviderErrorCategory.QUOTA_EXHAUSTED,
            root_cause=f"{provider_label} API 账户余额已耗尽或欠费停服 (Provider Credit Issue)",
            recommended_action=f"远端网络与服务正常，请前往 {provider_label} 官方控制台完成账户充值或切换备用提供方。",
            provider_name=provider_name,
            model_name=model_name,
        )

    # 2. 429 或命中限流特征词
    if status_code == 429 or any(kw in raw_text for kw in _RATE_LIMIT_KEYWORDS):
        provider_label = f"「{provider_name}」" if provider_name else "上游模型服务商"
        return ProviderQuotaClassification(
            is_provider_issue=True,
            category=ProviderErrorCategory.RATE_LIMITED,
            root_cause=f"{provider_label} 触发并发或吞吐速率限制 (Rate Limit Exceeded)",
            recommended_action="建议配置指数退避重试，或在路由中调高备用模型权重以分流并发压力。",
            provider_name=provider_name,
            model_name=model_name,
        )

    # 3. 401 或命中鉴权错误特征词
    if status_code == 401 or any(kw in raw_text for kw in _AUTH_KEYWORDS):
        provider_label = f"「{provider_name}」" if provider_name else "模型服务商"
        return ProviderQuotaClassification(
            is_provider_issue=True,
            category=ProviderErrorCategory.AUTH_INVALID,
            root_cause=f"{provider_label} API 密钥无效、已被注销或权限不足",
            recommended_action="请检查目标节点配置的 API Key 凭证有效性并重新录入。",
            provider_name=provider_name,
            model_name=model_name,
        )

    # 4. 503 / 502 / 504 服务端过载
    if status_code in (502, 503, 504) or "overloaded" in raw_text:
        provider_label = f"「{provider_name}」" if provider_name else "模型服务商"
        return ProviderQuotaClassification(
            is_provider_issue=True,
            category=ProviderErrorCategory.OVERLOADED,
            root_cause=f"{provider_label} 集群暂时过载或上游网关不可达",
            recommended_action="建议启用 Failover 自动故障转移，或稍后自动恢复重试。",
            provider_name=provider_name,
            model_name=model_name,
        )

    # 非已知 Provider 专属问题
    return ProviderQuotaClassification(
        is_provider_issue=False,
        category=ProviderErrorCategory.UNKNOWN,
        root_cause=f"上游返回 HTTP {status_code} 异常",
        recommended_action="检查具体请求载荷与日志排查原因。",
        provider_name=provider_name,
        model_name=model_name,
    )

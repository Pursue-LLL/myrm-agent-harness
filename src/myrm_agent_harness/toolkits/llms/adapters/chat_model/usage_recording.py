"""Token-usage recording shared by the sync and async ChatLiteLLM paths.

In streaming mode LiteLLM's own callbacks are skipped, so the adapter records usage,
cost and latency itself; non-streaming calls go through the same code so both paths
converge on the request-scoped ``TokenTracker`` and the audit ledger. Keeping it out
of the generation mixins leaves those files purely about the provider call.

[INPUT]
- adapters.streaming::normalize_usage (POS: LiteLLM usage 对象归一化)
- utils.token_economics.cost_engine::compute_cost_by_tokens (POS: 按 token 计价)
- utils.token_economics.usage_fields::extract_cost_tokens (POS: prompt/completion/cache 字段唯一读取入口)
- utils.token_economics.tracker::record_token_usage, append_to_ledger, record_finish_reason (POS: 请求级追踪与审计账本)

[OUTPUT]
- record_usage(): 记录一次调用的 usage、成本与延迟，并写入审计账本
- record_non_stream_usage(): 非流式响应的 finish_reason + usage 记录

[POS]
Usage accounting for the ChatLiteLLM adapter. Dependency-injected like the generation
helpers: callers pass the owner (``self``) so the model identity used for pricing comes
from the same instance that made the request.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class _ModelIdentity(Protocol):
    """The aggregate ``ChatLiteLLM`` attributes this module reads for pricing."""

    @property
    def model(self) -> str: ...


def record_usage(
    owner: _ModelIdentity,
    usage: Any,
    *,
    model_name: str = "",
    duration_ms: float | None = None,
    ttft_ms: float | None = None,
    finish_reason: str = "",
) -> None:
    """Record token usage, cost, and latency for an LLM response.

    Args:
        owner: the model instance the request ran on (pricing falls back to it).
        usage: LiteLLM usage object from the response / final stream chunk.
        model_name: Model identifier for per-model attribution.
        duration_ms: Total call duration (request start to completion).
        ttft_ms: Time to first token (streaming only).
        finish_reason: Model's finish reason (stop, tool_calls, max_tokens, etc.).
    """
    from myrm_agent_harness.toolkits.llms.adapters.streaming import normalize_usage
    from myrm_agent_harness.utils.token_economics.cost_engine import (
        compute_cost_by_tokens,
    )
    from myrm_agent_harness.utils.token_economics.tracker import (
        append_to_ledger,
        record_token_usage,
    )
    from myrm_agent_harness.utils.token_economics.usage_fields import extract_cost_tokens

    if not usage:
        return

    usage_dict = normalize_usage(usage)
    resolved_model = model_name or None
    request_model = getattr(owner, "model_name", None) or getattr(owner, "model", None)

    prompt_tokens, completion_tokens, cached_tokens, cache_write_tokens = extract_cost_tokens(usage_dict)

    cost_result = compute_cost_by_tokens(
        resolved_model,
        prompt_tokens,
        completion_tokens,
        cache_read_tokens=cached_tokens,
        cache_write_tokens=cache_write_tokens,
        request_model=request_model,
    )

    record_token_usage(
        usage_dict,
        model_name=resolved_model,
        duration_ms=duration_ms,
        ttft_ms=ttft_ms,
        cost_usd=cost_result.usd,
        cost_status=cost_result.status,
    )
    append_to_ledger(
        usage_dict,
        resolved_model,
        duration_ms,
        cost_result.usd,
        ttft_ms=ttft_ms,
        finish_reason=finish_reason,
    )


def record_non_stream_usage(
    owner: _ModelIdentity,
    response: Mapping[str, Any],
    *,
    model_name: str,
    duration_ms: float,
) -> None:
    """Record token usage and finish reason for a non-streaming response.

    Symmetric to the streaming path (``finalize_stream`` → ``record_usage``).
    Without this, non-streaming calls (orchestrators, summarizers, context
    compressors, ``llm_query``, ...) silently bypass the request-scoped
    ``TokenTracker`` and vanish from usage/cost reporting.
    """
    from myrm_agent_harness.utils.token_economics.tracker import record_finish_reason

    finish_reason = ""
    choices = response.get("choices") or []
    if choices and isinstance(choices[0], dict):
        finish_reason = str(choices[0].get("finish_reason") or "")

    if finish_reason:
        record_finish_reason(finish_reason)

    record_usage(
        owner,
        response.get("usage"),
        model_name=model_name,
        duration_ms=duration_ms,
        finish_reason=finish_reason,
    )

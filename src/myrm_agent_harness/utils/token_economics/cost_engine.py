"""Cost computation engine with provenance tracking and cache-aware pricing.

[INPUT]
- litellm (POS: LLM unified pricing interface, lazy import for token/completion cost calculation)
- response_obj / model / prompt_tokens / completion_tokens / cache_read_tokens / cache_write_tokens

[OUTPUT]
- CostStatus: Cost provenance enum (actual / estimated / unknown)
- CostResult: Computed cost in USD with provenance status
- compute_cost(): Calculate cost from response object via litellm.completion_cost()
- compute_cost_by_tokens(): Calculate cache-aware cost from token counts via litellm.cost_per_token()

[POS]
myrm_agent_harness 框架层核心 Token 经济基础设施。修复 litellm completion_cost 接口误用，
采用原生的 litellm.cost_per_token() 支持缓存读写折扣与供应商限定名/裸模型名双重解析，
彻底化解 LLM 费用恒为 unknown / 0 的确定性缺陷。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import logging

logger = logging.getLogger(__name__)


class CostStatus(StrEnum):
    """Cost provenance — how the cost figure was obtained."""

    ACTUAL = "actual"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CostResult:
    """Cost computation result with provenance."""

    usd: float = 0.0
    status: CostStatus = CostStatus.UNKNOWN

    @property
    def is_known(self) -> bool:
        return self.status != CostStatus.UNKNOWN


def compute_cost(
    response_obj: object,
    model: str | None,
) -> CostResult:
    """Compute cost via litellm.completion_cost(), returning CostResult with provenance.

    Returns CostResult(usd=0.0, status=UNKNOWN) on any failure.
    """
    if not model or response_obj is None:
        return CostResult()

    try:
        import litellm

        cost = float(litellm.completion_cost(completion_response=response_obj, model=model))
        if cost > 0:
            return CostResult(usd=cost, status=CostStatus.ACTUAL)
        return CostResult(usd=0.0, status=CostStatus.UNKNOWN)
    except Exception as exc:
        logger.debug("Cost computation from response_obj failed for model=%s: %s", model, exc)
        return CostResult()


def compute_cost_by_tokens(
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    custom_llm_provider: str | None = None,
    request_model: str | None = None,
) -> CostResult:
    """Compute cache-aware cost from token counts via litellm.cost_per_token().

    Used for streaming mode and turn-level usage calculation where complete
    response objects are not available. Accurately accounts for prompt tokens,
    completion tokens, cache read tokens, and cache creation tokens.

    Returns CostResult(usd=0.0, status=UNKNOWN) on pricing miss or computation failure.
    """
    target_model = (request_model or model or "").strip()
    if not target_model or (prompt_tokens <= 0 and completion_tokens <= 0):
        return CostResult()

    try:
        import litellm

        # 尝试首选目标模型名计价
        prompt_cost, comp_cost = _call_cost_per_token(
            litellm_module=litellm,
            model_name=target_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            custom_llm_provider=custom_llm_provider,
        )
        total_usd = float(prompt_cost + comp_cost)
        if total_usd > 0:
            return CostResult(usd=total_usd, status=CostStatus.ACTUAL)
        return CostResult(usd=0.0, status=CostStatus.UNKNOWN)
    except Exception as exc:
        logger.debug(
            "Primary token-based cost computation failed for model=%s (prompt=%d, comp=%d): %s",
            target_model,
            prompt_tokens,
            completion_tokens,
            exc,
        )

    # 尝试后备策略：若是供应商限定名，尝试剥离或使用 fallback provider 再次尝试
    try:
        import litellm

        candidate_model = target_model
        inferred_provider = custom_llm_provider
        if "/" in target_model:
            parts = target_model.split("/", 1)
            inferred_provider = inferred_provider or parts[0]
            candidate_model = parts[1]

        prompt_cost, comp_cost = _call_cost_per_token(
            litellm_module=litellm,
            model_name=candidate_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            custom_llm_provider=inferred_provider or "openai",
        )
        fallback_usd = float(prompt_cost + comp_cost)
        if fallback_usd > 0:
            return CostResult(usd=fallback_usd, status=CostStatus.ESTIMATED)
    except Exception:
        pass

    return CostResult()


def _call_cost_per_token(
    litellm_module: object,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    custom_llm_provider: str | None,
) -> tuple[float, float]:
    """底层调用 litellm.cost_per_token 并安全提取 (prompt_cost, completion_cost)."""
    cost_func = getattr(litellm_module, "cost_per_token")
    kwargs: dict[str, object] = {
        "model": model_name,
        "prompt_tokens": max(0, prompt_tokens),
        "completion_tokens": max(0, completion_tokens),
    }
    if cache_read_tokens > 0:
        kwargs["cache_read_input_tokens"] = cache_read_tokens
    if cache_write_tokens > 0:
        kwargs["cache_creation_input_tokens"] = cache_write_tokens
    if custom_llm_provider:
        kwargs["custom_llm_provider"] = custom_llm_provider

    res = cost_func(**kwargs)
    if isinstance(res, tuple) and len(res) >= 2:
        return float(res[0]), float(res[1])
    if isinstance(res, (int, float)):
        return float(res), 0.0
    return 0.0, 0.0


__all__ = [
    "CostStatus",
    "CostResult",
    "compute_cost",
    "compute_cost_by_tokens",
]

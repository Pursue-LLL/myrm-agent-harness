"""Evaluator for prompt cache destruction risk when modifying session configuration.

[INPUT]
- agent.context_management.cache_shield.cache_shield_types::CacheBreakEvaluation, CacheParameterKind,
  CacheRiskLevel (POS: Data contracts for cache break interception, cost impact evaluation, and smart cache
  branching.)

[OUTPUT]
- evaluate_parameter_mutation: Evaluates risk of prompt cache invalidation for configuration changes.

[POS]
Detects mid-flight parameter mutations that break provider cache keys, calculating cost penalties and advice.
"""

from __future__ import annotations

from .cache_shield_types import (
    CacheBreakEvaluation,
    CacheParameterKind,
    CacheRiskLevel,
)

DEFAULT_CACHE_ALERT_THRESHOLD = 8000
CRITICAL_CACHE_THRESHOLD = 30000


def evaluate_parameter_mutation(
    param_kind: CacheParameterKind,
    old_value: str,
    new_value: str,
    current_tokens: int,
    cache_alert_threshold: int = DEFAULT_CACHE_ALERT_THRESHOLD,
) -> CacheBreakEvaluation:
    """Evaluate whether mutating a configuration parameter mid-session will destroy prompt cache.

    Upstream providers (Anthropic, DeepSeek, OpenAI) use strict prefix cache keys composed of:
    Hash(model, system_prompt, tool_schemas, thinking_budget, message_prefix).
    Mutating model or thinking effort mid-session wipes upstream KV caches, triggering
    a full 1.0x prefill cost penalty and massive time-to-first-token spikes.
    """
    if old_value == new_value:
        return CacheBreakEvaluation(
            risk_level=CacheRiskLevel.SAFE,
            parameter_kind=param_kind,
            old_value=old_value,
            new_value=new_value,
            cached_tokens_at_risk=0,
            estimated_cost_multiplier_penalty=1.0,
            warning_message="No configuration mutation detected. Cache prefix is completely preserved.",
            recommended_action="apply_in_place",
            is_blocking_alert=False,
        )

    # Under threshold: cost of re-prefill is negligible
    if current_tokens < cache_alert_threshold:
        return CacheBreakEvaluation(
            risk_level=CacheRiskLevel.LOW,
            parameter_kind=param_kind,
            old_value=old_value,
            new_value=new_value,
            cached_tokens_at_risk=current_tokens,
            estimated_cost_multiplier_penalty=1.0,
            warning_message=(
                f"Session size ({current_tokens:,} tokens) is below alert threshold ({cache_alert_threshold:,}). "
                "Re-prefill cost is minimal."
            ),
            recommended_action="apply_in_place",
            is_blocking_alert=False,
        )

    # Over threshold: evaluate specific parameter impact
    if param_kind == CacheParameterKind.MODEL:
        is_critical = current_tokens >= CRITICAL_CACHE_THRESHOLD
        risk = CacheRiskLevel.CRITICAL if is_critical else CacheRiskLevel.HIGH
        warning = (
            f"Switching model from '{old_value}' to '{new_value}' wipes {current_tokens:,} cached tokens. "
            "Upstream providers maintain independent caches per model family. "
            "Next turn will incur a 10.0x prefill cost penalty and severe first-token latency spike."
        )
        return CacheBreakEvaluation(
            risk_level=risk,
            parameter_kind=param_kind,
            old_value=old_value,
            new_value=new_value,
            cached_tokens_at_risk=current_tokens,
            estimated_cost_multiplier_penalty=10.0,
            warning_message=warning,
            recommended_action="fork_branch",
            is_blocking_alert=True,
        )

    if param_kind == CacheParameterKind.THINKING_LEVEL:
        warning = (
            f"Modifying thinking level from '{old_value}' to '{new_value}' mutates the provider cache key. "
            f"Will invalidate {current_tokens:,} cached tokens and incur a 5.0x prefill recomputation penalty."
        )
        return CacheBreakEvaluation(
            risk_level=CacheRiskLevel.MEDIUM,
            parameter_kind=param_kind,
            old_value=old_value,
            new_value=new_value,
            cached_tokens_at_risk=current_tokens,
            estimated_cost_multiplier_penalty=5.0,
            warning_message=warning,
            recommended_action="fork_branch",
            is_blocking_alert=True,
        )

    # System prompt or tool set changes invalidate prefix from the start
    warning = (
        f"Modifying {param_kind.value} alters the root prompt prefix, invalidating all {current_tokens:,} cached tokens."
    )
    return CacheBreakEvaluation(
        risk_level=CacheRiskLevel.HIGH,
        parameter_kind=param_kind,
        old_value=old_value,
        new_value=new_value,
        cached_tokens_at_risk=current_tokens,
        estimated_cost_multiplier_penalty=10.0,
        warning_message=warning,
        recommended_action="fork_branch",
        is_blocking_alert=True,
    )

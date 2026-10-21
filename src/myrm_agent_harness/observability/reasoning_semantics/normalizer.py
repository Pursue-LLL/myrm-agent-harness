"""
[INPUT]: Raw provider usage maps, model identifiers, and custom cost rate overrides.
[OUTPUT]: NormalizedTokenUsageSnapshot adhering to strict zero-double-counting invariants.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/reasoning_semantics/normalizer.py
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .models import (
    NormalizedTokenUsageSnapshot,
    ReasoningInclusionPolicy,
)


class ProviderReasoningNormalizer:
    """
    Normalizes multi-provider LLM token usage into a unified semantics contract,
    guaranteeing that reasoning tokens are never double-counted in total tokens or bills.
    """

    _PROVIDER_POLICY_MAP: Dict[str, ReasoningInclusionPolicy] = {
        "openai": ReasoningInclusionPolicy.INCLUDED_IN_COMPLETION,
        "anthropic": ReasoningInclusionPolicy.INCLUDED_IN_COMPLETION,
        "deepseek": ReasoningInclusionPolicy.INCLUDED_IN_COMPLETION,
        "perplexity": ReasoningInclusionPolicy.INCLUDED_IN_COMPLETION,
        "vllm_standalone": ReasoningInclusionPolicy.STANDALONE_OUTPUT,
    }

    # Default rates: $0.003 / 1k prompt, $0.015 / 1k completion
    DEFAULT_PROMPT_RATE_PER_1K: float = 0.003
    DEFAULT_COMPLETION_RATE_PER_1K: float = 0.015

    def __init__(
        self,
        custom_policies: Optional[Dict[str, ReasoningInclusionPolicy]] = None,
    ) -> None:
        self._policies = dict(self._PROVIDER_POLICY_MAP)
        if custom_policies:
            self._policies.update(custom_policies)

    def resolve_policy(self, provider_or_model: str) -> ReasoningInclusionPolicy:
        norm = provider_or_model.strip().lower()
        for key, policy in self._policies.items():
            if key in norm:
                return policy
        # Default to standard industry norm: completion already contains reasoning tokens
        return ReasoningInclusionPolicy.INCLUDED_IN_COMPLETION

    def normalize(
        self,
        provider_or_model: str,
        raw_usage: Dict[str, Any],
        prompt_cost_per_1k: float = DEFAULT_PROMPT_RATE_PER_1K,
        completion_cost_per_1k: float = DEFAULT_COMPLETION_RATE_PER_1K,
    ) -> NormalizedTokenUsageSnapshot:
        policy = self.resolve_policy(provider_or_model)

        # 1. Extract prompt tokens
        prompt = int(raw_usage.get("prompt_tokens") or raw_usage.get("input_tokens") or 0)

        # 2. Extract completion tokens
        raw_completion = int(raw_usage.get("completion_tokens") or raw_usage.get("output_tokens") or 0)

        # 3. Extract reasoning tokens from various vendor conventions
        raw_reasoning = 0
        if "reasoning_tokens" in raw_usage:
            raw_reasoning = int(raw_usage["reasoning_tokens"])
        elif "thinking_tokens" in raw_usage:
            raw_reasoning = int(raw_usage["thinking_tokens"])
        elif "completion_tokens_details" in raw_usage and isinstance(raw_usage["completion_tokens_details"], dict):
            details = raw_usage["completion_tokens_details"]
            raw_reasoning = int(details.get("reasoning_tokens") or 0)

        # 4. Apply policy normalization
        if policy == ReasoningInclusionPolicy.STANDALONE_OUTPUT:
            # Standalone gateway: raw_completion was just visible output, total completion must sum them
            unified_completion = raw_completion + raw_reasoning
            visible_content = raw_completion
        else:
            # Standard (OpenAI / Anthropic / DeepSeek): raw_completion ALREADY includes reasoning
            unified_completion = raw_completion
            visible_content = max(0, unified_completion - raw_reasoning)

        # 5. Invariant enforcement: total_tokens == prompt_tokens + unified_completion
        # If upstream passed a double-counted total, discard it and use strict invariant
        unified_total = prompt + unified_completion

        # 6. Cost calculation: NEVER double charge for reasoning tokens
        cost_usd = round(
            (prompt / 1000.0) * prompt_cost_per_1k
            + (unified_completion / 1000.0) * completion_cost_per_1k,
            5,
        )

        now_str = datetime.now(timezone.utc).isoformat()

        return NormalizedTokenUsageSnapshot(
            prompt_tokens=prompt,
            completion_tokens=unified_completion,
            reasoning_tokens=raw_reasoning,
            visible_content_tokens=visible_content,
            total_tokens=unified_total,
            cost_usd=cost_usd,
            is_zero_double_counted=True,
            raw_provider=provider_or_model,
            policy_applied=policy,
            normalized_at=now_str,
        )

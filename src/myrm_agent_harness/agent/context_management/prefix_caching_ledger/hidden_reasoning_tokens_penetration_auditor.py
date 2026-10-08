# [INPUT]: TokenUsageBreakdown
# [OUTPUT]: HiddenReasoningTokensPenetrationAuditor
# [POS]: agent/context_management/prefix_caching_ledger/hidden_reasoning_tokens_penetration_auditor.py

"""Auditor extracting hidden reasoning tokens and prefix cache usage across heterogeneous providers.

[INPUT]
- TokenUsageBreakdown: Standardized audited token container.

[OUTPUT]
- HiddenReasoningTokensPenetrationAuditor: Normalizes raw provider usage payloads into verified breakdowns.

[POS]
Provider telemetry penetration layer ensuring zero unbilled token blind spots.
"""

from __future__ import annotations

from typing import Mapping

from .prefix_caching_types import TokenUsageBreakdown


class HiddenReasoningTokensPenetrationAuditor:
    """Extracts hidden reasoning and cache read/write tokens from raw provider responses."""

    @staticmethod
    def _safe_int(value: object) -> int:
        """Safely convert arbitrary scalar value to integer with zero fallback."""
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return 0
        return 0

    def audit_raw_usage(self, raw_payload: Mapping[str, object]) -> TokenUsageBreakdown:
        """Parse heterogeneous raw provider payload into unified TokenUsageBreakdown.

        Supports schemas from:
        - OpenAI: prompt_tokens, completion_tokens, completion_tokens_details.reasoning_tokens, prompt_tokens_details.cached_tokens
        - Anthropic: input_tokens, output_tokens, thinking_tokens, cache_read_input_tokens, cache_creation_input_tokens
        - DeepSeek: prompt_tokens, completion_tokens, prompt_cache_hit_tokens, reasoning_tokens
        - Gemini: prompt_token_count, candidates_token_count, cached_content_token_count, thoughts_token_count
        """
        if not raw_payload:
            return TokenUsageBreakdown()

        # Extract root or nested 'usage' dictionary
        usage_dict: Mapping[str, object]
        nested_usage = raw_payload.get("usage")
        if isinstance(nested_usage, Mapping):
            usage_dict = nested_usage
        else:
            usage_dict = raw_payload

        # 1. Base Input Tokens
        input_tokens = (
            self._safe_int(usage_dict.get("prompt_tokens"))
            or self._safe_int(usage_dict.get("input_tokens"))
            or self._safe_int(usage_dict.get("prompt_token_count"))
        )

        # 2. Base Output Tokens
        output_tokens = (
            self._safe_int(usage_dict.get("completion_tokens"))
            or self._safe_int(usage_dict.get("output_tokens"))
            or self._safe_int(usage_dict.get("candidates_token_count"))
        )

        # 3. Penetrate Hidden Reasoning Tokens
        reasoning_tokens = 0
        # Check top-level thinking keys
        if "reasoning_tokens" in usage_dict:
            reasoning_tokens = self._safe_int(usage_dict.get("reasoning_tokens"))
        elif "thinking_tokens" in usage_dict:
            reasoning_tokens = self._safe_int(usage_dict.get("thinking_tokens"))
        elif "thoughts_token_count" in usage_dict:
            reasoning_tokens = self._safe_int(usage_dict.get("thoughts_token_count"))

        # Check OpenAI / DeepSeek completion_tokens_details
        comp_details = usage_dict.get("completion_tokens_details")
        if isinstance(comp_details, Mapping):
            details_reasoning = self._safe_int(comp_details.get("reasoning_tokens"))
            if details_reasoning > 0:
                reasoning_tokens = max(reasoning_tokens, details_reasoning)

        # Check Anthropic output_tokens_details
        output_details = usage_dict.get("output_tokens_details")
        if isinstance(output_details, Mapping):
            details_thinking = self._safe_int(output_details.get("thinking_tokens"))
            if details_thinking > 0:
                reasoning_tokens = max(reasoning_tokens, details_thinking)

        # 4. Penetrate Cache Read Tokens
        cache_read_tokens = 0
        if "cache_read_input_tokens" in usage_dict:
            cache_read_tokens = self._safe_int(usage_dict.get("cache_read_input_tokens"))
        elif "prompt_cache_hit_tokens" in usage_dict:
            cache_read_tokens = self._safe_int(usage_dict.get("prompt_cache_hit_tokens"))
        elif "cached_content_token_count" in usage_dict:
            cache_read_tokens = self._safe_int(usage_dict.get("cached_content_token_count"))

        prompt_details = usage_dict.get("prompt_tokens_details")
        if isinstance(prompt_details, Mapping):
            details_cached = self._safe_int(prompt_details.get("cached_tokens"))
            if details_cached > 0:
                cache_read_tokens = max(cache_read_tokens, details_cached)

        # 5. Penetrate Cache Write / Creation Tokens
        cache_write_tokens = 0
        if "cache_creation_input_tokens" in usage_dict:
            cache_write_tokens = self._safe_int(usage_dict.get("cache_creation_input_tokens"))
        elif "prompt_cache_miss_tokens" in usage_dict:
            cache_write_tokens = self._safe_int(usage_dict.get("prompt_cache_miss_tokens"))

        return TokenUsageBreakdown(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )

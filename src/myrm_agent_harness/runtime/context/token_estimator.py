"""Dual-track token estimator with provider usage anchor and orthogonal compaction gate.

[INPUT]
- langchain_core.messages::AIMessage, BaseMessage, HumanMessage, ToolMessage
- utils.token_estimation::estimate_message_tokens, estimate_messages_tokens

[OUTPUT]
- CompactionBudgetSettings: Orthogonal dual-budget model (reserve vs keep_recent)
- ProviderUsageAnchor: Extracted provider-reported usage anchor dataclass
- extract_provider_usage_anchor: Reverse scan for latest authoritative usage
- estimate_context_tokens_anchored: Fast-forward anchored estimator (O(1) tail increment)
- is_compaction_triggered: Strict reserve-gate predicate

[POS]
Harness runtime context layer. Provides high-throughput, drift-free token estimation
anchored on provider billing data for context management decisions.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from langchain_core.messages import AIMessage, BaseMessage

from myrm_agent_harness.utils.token_estimation import (
    estimate_message_tokens,
    estimate_messages_tokens,
)

DEFAULT_RESERVE_TOKENS: Final[int] = 16384
DEFAULT_KEEP_RECENT_TOKENS: Final[int] = 20000
DEFAULT_SUMMARY_RESERVE_RATIO: Final[float] = 0.80


@dataclass(slots=True, frozen=True)
class ProviderUsageAnchor:
    """Authoritative provider usage anchor point."""

    anchor_index: int
    prompt_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(slots=True, frozen=True)
class CompactionBudgetSettings:
    """Orthogonal dual-budget configuration model.

    Distinguishes reserve_tokens (trigger barrier & summary ceiling) from
    keep_recent_tokens (retained tail volume post-compaction).
    """

    reserve_tokens: int = DEFAULT_RESERVE_TOKENS
    keep_recent_tokens: int = DEFAULT_KEEP_RECENT_TOKENS
    summary_reserve_ratio: float = DEFAULT_SUMMARY_RESERVE_RATIO

    def is_triggered(self, context_tokens: int, context_window: int) -> bool:
        """Evaluate if context tokens cross the compaction trigger threshold."""
        return is_compaction_triggered(context_tokens, context_window, self.reserve_tokens)

    def max_summary_tokens(self, model_max_tokens: int | None = None) -> int:
        """Calculate summary generation output token budget ceiling."""
        budget = math.floor(self.reserve_tokens * self.summary_reserve_ratio)
        if model_max_tokens is not None and model_max_tokens > 0:
            return min(budget, model_max_tokens)
        return budget


def extract_provider_usage_anchor(messages: Sequence[BaseMessage]) -> ProviderUsageAnchor | None:
    """Reverse scan for the latest AIMessage containing valid provider usage metrics.

    Scans backwards from the most recent message to identify the closest turn
    that completed a real LLM round-trip with vendor token usage.
    """
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if not isinstance(msg, AIMessage):
            continue

        usage_meta = getattr(msg, "usage_metadata", None)
        if isinstance(usage_meta, dict):
            prompt = usage_meta.get("input_tokens") or usage_meta.get("prompt_tokens") or 0
            output = usage_meta.get("output_tokens") or usage_meta.get("completion_tokens") or 0
            total = usage_meta.get("total_tokens") or (prompt + output)
            if isinstance(prompt, int) and prompt > 0:
                out_int = int(output) if isinstance(output, int) else 0
                tot_int = int(total) if isinstance(total, int) else (prompt + out_int)
                return ProviderUsageAnchor(
                    anchor_index=idx,
                    prompt_tokens=prompt,
                    output_tokens=out_int,
                    total_tokens=tot_int,
                )

        resp_meta = getattr(msg, "response_metadata", None)
        if isinstance(resp_meta, dict):
            usage = resp_meta.get("usage") or resp_meta.get("token_usage")
            if isinstance(usage, dict):
                prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
                output = usage.get("completion_tokens") or usage.get("output_tokens") or 0
                total = usage.get("total_tokens") or (prompt + output)
                if isinstance(prompt, int) and prompt > 0:
                    out_int = int(output) if isinstance(output, int) else 0
                    tot_int = int(total) if isinstance(total, int) else (prompt + out_int)
                    return ProviderUsageAnchor(
                        anchor_index=idx,
                        prompt_tokens=prompt,
                        output_tokens=out_int,
                        total_tokens=tot_int,
                    )

        add_kwargs = getattr(msg, "additional_kwargs", None)
        if isinstance(add_kwargs, dict):
            usage = add_kwargs.get("usage")
            if isinstance(usage, dict):
                prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
                output = usage.get("completion_tokens") or usage.get("output_tokens") or 0
                total = usage.get("total_tokens") or (prompt + output)
                if isinstance(prompt, int) and prompt > 0:
                    out_int = int(output) if isinstance(output, int) else 0
                    tot_int = int(total) if isinstance(total, int) else (prompt + out_int)
                    return ProviderUsageAnchor(
                        anchor_index=idx,
                        prompt_tokens=prompt,
                        output_tokens=out_int,
                        total_tokens=tot_int,
                    )

    return None


def estimate_context_tokens_anchored(
    messages: Sequence[BaseMessage],
    *,
    bound_tool_overhead_tokens: int = 0,
    fallback_on_no_anchor: bool = True,
) -> tuple[int, bool]:
    """Fast-forward token estimator anchored on authoritative provider usage.

    Algorithm:
    1. Reverse search for the newest AIMessage with provider usage.
    2. If found, baseline = anchor.prompt_tokens (which covers system prompt,
       all preceding history, and bound tool definitions at that invocation).
    3. Incrementally accumulate the anchor AIMessage's own output tokens, plus
       all newly appended tail messages (ToolMessage / HumanMessage).
    4. If no anchor exists, fallback smoothly to full estimate_messages_tokens.

    Returns:
        (estimated_tokens, is_anchored)
    """
    if not messages:
        return max(0, bound_tool_overhead_tokens), False

    anchor = extract_provider_usage_anchor(messages)
    if anchor is not None:
        # Start from authoritative input tokens reported by the model provider
        incremental_tokens = 0

        # Anchor message's own output tokens
        if anchor.output_tokens > 0:
            incremental_tokens += anchor.output_tokens
        else:
            incremental_tokens += estimate_message_tokens(messages[anchor.anchor_index])

        # Incrementally sum all subsequent messages appended after the anchor
        for tail_idx in range(anchor.anchor_index + 1, len(messages)):
            incremental_tokens += estimate_message_tokens(messages[tail_idx])

        total = anchor.prompt_tokens + incremental_tokens
        return total, True

    if not fallback_on_no_anchor:
        return 0, False

    full_estimate = estimate_messages_tokens(list(messages)) + max(0, bound_tool_overhead_tokens)
    return full_estimate, False


def is_compaction_triggered(
    context_tokens: int,
    context_window: int,
    reserve_tokens: int = DEFAULT_RESERVE_TOKENS,
) -> bool:
    """Strict reserve-gate check determining whether compaction must fire.

    Fires when current context exceeds (context_window - reserve_tokens).
    """
    trigger_threshold = max(0, context_window - max(0, reserve_tokens))
    return context_tokens > trigger_threshold

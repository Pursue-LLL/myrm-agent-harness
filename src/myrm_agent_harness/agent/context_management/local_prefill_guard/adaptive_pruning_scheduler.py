"""Adaptive pruning scheduler tailoring context compression for local LLMs.

[INPUT]
- local_prefill_types::AdaptivePruningDecision, PruningPolicyTier, LocalEndpointProfile, PrefillLatencyEstimate, PrunedResultSummary (POS: Local prefill types)
- endpoint_inspector_and_ttft_estimator::TtftLatencyEstimator (POS: Latency estimator)
- langchain_core.messages::BaseMessage, AIMessage, ToolMessage (POS: LangChain message abstractions)
- utils.token_estimation::estimate_content_tokens (POS: Token counter utility)

[OUTPUT]
- LocalAdaptivePruningScheduler: Dynamic pruning policy evaluator and execution engine.

[POS]
Adaptive pruning scheduler dynamically shrinking tool result retention thresholds
(down to 512 or 256 tokens) when local endpoints face catastrophic TTFT overhead.
"""

from __future__ import annotations

import re
from typing import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from myrm_agent_harness.utils.token_estimation import estimate_content_tokens

from .endpoint_inspector_and_ttft_estimator import TtftLatencyEstimator
from .local_prefill_types import (
    AdaptivePruningDecision,
    LatencyWarningLevel,
    LocalEndpointProfile,
    PrefillLatencyEstimate,
    PrunedResultSummary,
    PruningPolicyTier,
)


class LocalAdaptivePruningScheduler:
    """Calculates and executes adaptive pruning decisions geared for local inference."""

    @classmethod
    def compute_decision(
        cls,
        current_tokens: int,
        profile: LocalEndpointProfile,
        estimate: PrefillLatencyEstimate | None = None,
    ) -> AdaptivePruningDecision:
        """Derive the optimal pruning policy tier and numerical limits."""
        est = estimate or TtftLatencyEstimator.estimate_ttft(current_tokens, profile)

        if not profile.is_local:
            return AdaptivePruningDecision(
                policy_tier=PruningPolicyTier.CONSERVATIVE_CLOUD,
                threshold_tokens=2048,
                keep_recent_calls=5,
                min_reclaim_tokens=0,
                head_chars=800,
                tail_chars=400,
                reason="Cloud API target: standard 2048 token pruning threshold.",
            )

        # Local model adaptive tier calculation
        if est.warning_level == LatencyWarningLevel.FREEZE_RISK or current_tokens >= 49152:
            return AdaptivePruningDecision(
                policy_tier=PruningPolicyTier.EMERGENCY_SHEDDING,
                threshold_tokens=256,
                keep_recent_calls=1,
                min_reclaim_tokens=0,
                head_chars=160,
                tail_chars=80,
                reason=f"Emergency shedding: TTFT projection {est.estimated_ttft_seconds}s triggers aggressive 256-token threshold.",
            )

        if est.suggests_aggressive_pruning or current_tokens >= 16384:
            return AdaptivePruningDecision(
                policy_tier=PruningPolicyTier.AGGRESSIVE_LOCAL_32K,
                threshold_tokens=512,
                keep_recent_calls=2,
                min_reclaim_tokens=0,
                head_chars=320,
                tail_chars=160,
                reason=f"Aggressive local pruning: TTFT projection {est.estimated_ttft_seconds}s triggers 512-token threshold.",
            )

        return AdaptivePruningDecision(
            policy_tier=PruningPolicyTier.BALANCED_LOCAL,
            threshold_tokens=1024,
            keep_recent_calls=3,
            min_reclaim_tokens=0,
            head_chars=600,
            tail_chars=300,
            reason="Balanced local pruning: moderate 1024-token threshold.",
        )

    @classmethod
    def prune_messages(
        cls,
        messages: Sequence[BaseMessage],
        decision: AdaptivePruningDecision,
    ) -> tuple[list[BaseMessage], list[PrunedResultSummary], int]:
        """Execute deterministic adaptive pruning on messages based on computed decision.

        Returns:
            Tuple of (pruned_messages, summaries, total_tokens_saved).
        """
        msg_list = list(messages)
        cutoff = cls._find_recent_tool_cutoff(msg_list, decision.keep_recent_calls)
        if cutoff <= 0:
            return msg_list, [], 0

        summaries: list[PrunedResultSummary] = []
        tokens_saved_total = 0

        for idx in range(cutoff):
            msg = msg_list[idx]
            if not isinstance(msg, ToolMessage):
                continue

            # Must be consumed by at least one subsequent AIMessage
            if not cls._is_consumed_by_assistant(msg_list, idx):
                continue

            content_text = cls._extract_text(msg.content)
            if not content_text:
                continue

            original_tokens = estimate_content_tokens(content_text)
            if original_tokens <= decision.threshold_tokens:
                continue

            # Compact the content into a lightweight placeholder preserving findings
            placeholder = cls._build_compact_placeholder(
                tool_name=msg.name or "tool",
                content=content_text,
                original_tokens=original_tokens,
                decision=decision,
            )
            compact_tokens = estimate_content_tokens(placeholder)

            if compact_tokens < original_tokens:
                saved = original_tokens - compact_tokens
                tokens_saved_total += saved
                updated_msg = cls._copy_tool_message(msg, placeholder)
                msg_list[idx] = updated_msg

                snippet = placeholder[:80].replace("\n", " ").strip()
                summaries.append(
                    PrunedResultSummary(
                        tool_name=msg.name or "unknown",
                        tool_call_id=msg.tool_call_id or "",
                        original_tokens=original_tokens,
                        pruned_tokens=compact_tokens,
                        saved_tokens=saved,
                        snippet_preview=snippet,
                    )
                )

        return msg_list, summaries, tokens_saved_total

    @classmethod
    def _is_consumed_by_assistant(cls, messages: list[BaseMessage], tool_idx: int) -> bool:
        return any(isinstance(messages[i], AIMessage) for i in range(tool_idx + 1, len(messages)))

    @classmethod
    def _find_recent_tool_cutoff(cls, messages: list[BaseMessage], keep_recent_calls: int) -> int:
        if keep_recent_calls <= 0:
            return len(messages)
        count = 0
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], ToolMessage):
                count += 1
                if count >= keep_recent_calls:
                    return i
        return 0

    @classmethod
    def _extract_text(cls, content: object) -> str | None:
        return content if isinstance(content, str) else None

    @classmethod
    def _build_compact_placeholder(
        cls,
        *,
        tool_name: str,
        content: str,
        original_tokens: int,
        decision: AdaptivePruningDecision,
    ) -> str:
        orig_len = len(content)
        head_len = decision.head_chars
        tail_len = decision.tail_chars

        if orig_len <= head_len + tail_len:
            return content

        findings = ""
        error_match = re.search(
            r"(?:(?:error|exception|fail(?:ed)?|assertionerror|traceback|panic)[:\s][^\n]{0,80})",
            content,
            re.IGNORECASE,
        )
        if error_match:
            findings = f" Key finding: {error_match.group(0).strip()}."

        marker = (
            f"[Local Prefill Guard: Pruned {tool_name} output (~{original_tokens} tokens down to compact form, "
            f"tier={decision.policy_tier.value}).{findings}]"
        )

        head = content[:head_len]
        tail = content[-tail_len:] if tail_len > 0 else ""
        return f"{head}\n\n{marker}\n\n{tail}"

    @classmethod
    def _copy_tool_message(cls, msg: ToolMessage, new_content: str) -> ToolMessage:
        if hasattr(msg, "model_copy"):
            return msg.model_copy(update={"content": new_content})
        return msg.copy(update={"content": new_content})

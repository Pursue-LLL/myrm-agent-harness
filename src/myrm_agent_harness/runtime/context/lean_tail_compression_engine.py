"""Lean-Tail compaction engine with fixed-interval tail bounds and soft token budgeting.

Implements Hermes Agent v0.20.6 lean-tail architecture:
1. Fixed-interval tail protection (floor 10k ~ cap 25k tokens).
2. Sub-512K context window 75% threshold floor.
3. Prompt-level soft token target guidance without wire-level max_tokens deadlocks.
4. Seamless integration with ReasoningTraceStripper.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.lean_tail_compression_types import (
    LeanTailCompactionPlan,
    LeanTailConfig,
    LeanTailWindowBudget,
)
from myrm_agent_harness.runtime.context.reasoning_trace_stripper import (
    ReasoningTraceStripper,
)


class LeanTailCompressionEngine:
    """Orchestrates lean-tail history compaction with reasoning trace sanitization."""

    def __init__(
        self,
        config: LeanTailConfig | None = None,
        stripper: ReasoningTraceStripper | None = None,
    ) -> None:
        self.config = config or LeanTailConfig()
        self.stripper = stripper or ReasoningTraceStripper(self.config.target_tags)

    def calculate_budget(self, context_window_size: int) -> LeanTailWindowBudget:
        """Calculate dynamic threshold and bounded tail protection budget."""
        is_sub_512k = context_window_size < 512_000

        # Sub-512K models enforce a 75% compression threshold floor
        if is_sub_512k:
            effective_threshold = max(
                self.config.default_trigger_threshold,
                self.config.sub_512k_threshold_floor,
            )
            is_floored = True
        else:
            effective_threshold = self.config.default_trigger_threshold
            is_floored = False

        trigger_tokens = int(context_window_size * effective_threshold)

        # Bound protected tail tokens strictly within [floor_tokens, cap_tokens]
        # (Default: 10,000 to 25,000 tokens)
        tail_candidate = int(context_window_size * 0.10)
        protected_tail_tokens = max(
            self.config.floor_tokens,
            min(self.config.cap_tokens, tail_candidate),
        )

        return LeanTailWindowBudget(
            context_window_size=context_window_size,
            effective_threshold=effective_threshold,
            trigger_tokens=trigger_tokens,
            protected_tail_tokens=protected_tail_tokens,
            is_floored_to_75_percent=is_floored,
        )

    def plan_compaction(
        self,
        messages: list[dict[str, str]],
        context_window_size: int,
        estimated_total_tokens: int | None = None,
    ) -> LeanTailCompactionPlan:
        """Evaluate messages and devise lean-tail compaction split."""
        budget = self.calculate_budget(context_window_size)
        total_tokens = (
            estimated_total_tokens
            if estimated_total_tokens is not None
            else self.estimate_messages_tokens(messages)
        )

        needs_compaction = total_tokens >= budget.trigger_tokens
        if not needs_compaction or len(messages) <= 2:
            return LeanTailCompactionPlan(
                total_tokens=total_tokens,
                budget=budget,
                needs_compaction=False,
                messages_to_compact_count=0,
                protected_tail_messages_count=len(messages),
                summarizer_prompt_instructions="",
            )

        # Walk backward from tail to allocate protected recent messages
        tail_accumulated_tokens = 0
        tail_count = 0

        for msg in reversed(messages):
            msg_tokens = max(1, len(msg.get("content", "")) // 4)
            if tail_accumulated_tokens + msg_tokens <= budget.protected_tail_tokens:
                tail_accumulated_tokens += msg_tokens
                tail_count += 1
            else:
                break

        # Ensure at least 1 recent message in tail and at least 1 to compact
        tail_count = max(1, min(len(messages) - 1, tail_count))
        compact_count = len(messages) - tail_count

        soft_instructions = (
            f"Please synthesize the preceding history into a concise summary.\n"
            f"- Target summary volume: ~{self.config.target_summary_tokens} tokens.\n"
            f"- Retain essential decisions, files created/modified, and unfinished objectives.\n"
            f"- Do NOT emit <think> or internal reasoning tags in your output."
        )

        return LeanTailCompactionPlan(
            total_tokens=total_tokens,
            budget=budget,
            needs_compaction=True,
            messages_to_compact_count=compact_count,
            protected_tail_messages_count=tail_count,
            summarizer_prompt_instructions=soft_instructions,
        )

    def prepare_summarizer_input(
        self, messages_to_compact: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        """Strip reasoning traces from historical messages before presenting to summarizer."""
        return self.stripper.strip_messages(messages_to_compact)

    def finalize_summary(self, raw_summary_text: str) -> str:
        """Strip any thoughts generated by the summarizer model before persisting."""
        return self.stripper.strip_summarizer_output(raw_summary_text)

    def assemble_compacted_messages(
        self,
        system_message: dict[str, str],
        summary_text: str,
        protected_tail_messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Combine system prompt, cleaned summary anchor, and protected lean tail."""
        cleaned_summary = self.finalize_summary(summary_text)
        summary_msg = {
            "role": "user",
            "content": (
                f"<compacted_history_summary>\n"
                f"{cleaned_summary}\n"
                f"</compacted_history_summary>"
            ),
        }
        return [dict(system_message), summary_msg, *[dict(m) for m in protected_tail_messages]]

    @staticmethod
    def estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
        """Fast character-heuristic token estimator (4 chars ~= 1 token)."""
        return sum(max(1, len(m.get("content", "")) // 4) for m in messages)

"""Dual-Tier Micro/Full Adaptive Compactor and Mid-Task Steering Engine.

Reference: Alibaba Qianwen App Office Mode query2() kernel.
Implements:
1. Micro-compact: 0-cost rule-based historical tool output folding (saves 40%-60% tokens instantly).
2. Full-compact: Seamless escalation to deep semantic compaction when micro-compact is insufficient.
3. SteerQueue: Thread-safe mid-task user instruction queuing and dynamic prompt injection.
Strict 0 Any, type-hinted, thread-safe.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Sequence

from .dual_tier_compactor_types import (
    CompactorTierKind,
    DualTierCompactorDecision,
    MicroFoldedItem,
    SteerInstruction,
)
from .pi_progressive_compactor import PiProgressiveCompactor
from .surface_projection_types import MessageRole, ProjectedMessage


class SteerQueue:
    """Thread-safe mid-task user steering instruction queue."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._queue: list[SteerInstruction] = []
        self._seq: int = 0

    def enqueue(self, content: str, priority: int = 1) -> SteerInstruction:
        """Enqueue a user dynamic steering command."""
        with self._lock:
            self._seq += 1
            inst = SteerInstruction(
                instruction_id=f"steer-{self._seq}",
                content=content.strip(),
                timestamp=time.time(),
                priority=priority,
            )
            self._queue.append(inst)
            return inst

    def drain(self) -> tuple[SteerInstruction, ...]:
        """Atomically drain all pending steering instructions."""
        with self._lock:
            drained = tuple(self._queue)
            self._queue.clear()
            return drained

    def peek(self) -> tuple[SteerInstruction, ...]:
        """Inspect pending steering instructions without draining."""
        with self._lock:
            return tuple(self._queue)

    @staticmethod
    def render_steer_prompt_block(steers: Sequence[SteerInstruction]) -> str:
        """Render instructions into an XML block for the next agent inference turn."""
        if not steers:
            return ""

        lines = ["<mid_task_user_steering>"]
        for s in steers:
            lines.append(f"  <instruction id='{s.instruction_id}' priority='{s.priority}'>")
            lines.append(f"    {s.content}")
            lines.append("  </instruction>")
        lines.append("</mid_task_user_steering>")
        return "\n".join(lines)


class DualTierAdaptiveCompactor:
    """Dual-tier progressive compactor with micro/full adaptive escalation."""

    @classmethod
    def estimate_tokens(cls, message: ProjectedMessage) -> int:
        """Estimate token consumption via chars // 4."""
        chars = len(message.content or "")
        if message.reasoning_content:
            chars += len(message.reasoning_content)
        if message.tool_calls:
            chars += sum(len(tc) for tc in message.tool_calls)
        return max(1, math.ceil(chars / 4))

    @classmethod
    def evaluate_and_compact(
        cls,
        messages: Sequence[ProjectedMessage],
        context_window: int = 128000,
        micro_threshold_ratio: float = 0.65,
        full_threshold_ratio: float = 0.85,
        preserve_recent_turns: int = 2,
        min_fold_chars: int = 500,
    ) -> tuple[tuple[ProjectedMessage, ...], DualTierCompactorDecision]:
        """Execute dual-tier adaptive compaction.

        1. If tokens < micro threshold, return as-is.
        2. If tokens >= micro threshold, execute zero-cost Micro-compact (rule-based tool folding).
        3. If tokens still >= full threshold after Micro-compact, escalate to Full-compact (Pi summarizer).
        """
        orig_tokens = sum(cls.estimate_tokens(m) for m in messages)
        micro_threshold = int(context_window * micro_threshold_ratio)
        full_threshold = int(context_window * full_threshold_ratio)

        # Tier 0: No compaction needed
        if orig_tokens < micro_threshold:
            decision = DualTierCompactorDecision(
                tier=CompactorTierKind.NONE,
                triggered=False,
                tokens_before=orig_tokens,
                tokens_after=orig_tokens,
                saved_tokens=0,
                folded_items=(),
                details=f"Context tokens {orig_tokens} is below micro threshold {micro_threshold}.",
            )
            return tuple(messages), decision

        # Tier 1: Micro-compact (rule-based tool output folding)
        micro_messages, folded_items = cls._apply_micro_compact(
            messages=messages,
            preserve_recent_turns=preserve_recent_turns,
            min_fold_chars=min_fold_chars,
        )
        tokens_after_micro = sum(cls.estimate_tokens(m) for m in micro_messages)
        micro_saved = orig_tokens - tokens_after_micro

        # Check if micro-compact successfully resolved the pressure
        if tokens_after_micro < full_threshold:
            decision = DualTierCompactorDecision(
                tier=CompactorTierKind.MICRO,
                triggered=True,
                tokens_before=orig_tokens,
                tokens_after=tokens_after_micro,
                saved_tokens=micro_saved,
                folded_items=folded_items,
                details=(
                    f"Micro-compact folded {len(folded_items)} historical tool results, "
                    f"saving {micro_saved} tokens ({tokens_after_micro}/{context_window})."
                ),
            )
            return micro_messages, decision

        # Tier 2: Escalate to Full-compact (deep semantic restructuring)
        full_result = PiProgressiveCompactor.compact(
            messages=micro_messages,
        )
        tokens_after_full = full_result.tokens_after
        total_saved = orig_tokens - tokens_after_full

        decision = DualTierCompactorDecision(
            tier=CompactorTierKind.FULL,
            triggered=True,
            tokens_before=orig_tokens,
            tokens_after=tokens_after_full,
            saved_tokens=total_saved,
            folded_items=folded_items,
            details=(
                f"Full-compact escalated: micro folded {len(folded_items)} tool results, "
                f"then deep semantic compaction reduced context to {tokens_after_full} tokens."
            ),
        )
        return full_result.projected_messages, decision

    @classmethod
    def _apply_micro_compact(
        cls,
        messages: Sequence[ProjectedMessage],
        preserve_recent_turns: int,
        min_fold_chars: int,
    ) -> tuple[tuple[ProjectedMessage, ...], tuple[MicroFoldedItem, ...]]:
        """Fold oversized historical tool outputs outside the preserved recent turn window."""
        result_messages: list[ProjectedMessage] = list(messages)
        folded_items: list[MicroFoldedItem] = []

        # Find boundary of preserved recent turns by counting user messages from tail
        user_turn_count = 0
        cutoff_index = 0
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == MessageRole.USER:
                user_turn_count += 1
                if user_turn_count >= preserve_recent_turns:
                    cutoff_index = i
                    break

        # Process messages before the cutoff index
        for idx in range(cutoff_index):
            msg = result_messages[idx]
            if msg.role == MessageRole.TOOL:
                content = msg.content or ""
                if len(content) > min_fold_chars:
                    tool_name = msg.name or "tool"
                    folded_content = (
                        f"[Tool Output Folded ({tool_name}): {len(content)} chars "
                        f"summarized/omitted to preserve context window]"
                    )
                    folded_msg = ProjectedMessage(
                        role=MessageRole.TOOL,
                        content=folded_content,
                        tool_call_id=msg.tool_call_id,
                        name=msg.name,
                    )
                    orig_tokens = cls.estimate_tokens(msg)
                    new_tokens = cls.estimate_tokens(folded_msg)
                    saved = max(0, orig_tokens - new_tokens)

                    result_messages[idx] = folded_msg
                    folded_items.append(
                        MicroFoldedItem(
                            index=idx,
                            tool_name=tool_name,
                            original_chars=len(content),
                            folded_chars=len(folded_content),
                            saved_tokens=saved,
                        )
                    )

        return tuple(result_messages), tuple(folded_items)

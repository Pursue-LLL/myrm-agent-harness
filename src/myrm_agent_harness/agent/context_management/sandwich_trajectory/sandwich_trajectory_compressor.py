"""Core implementation of Sandwich Trajectory Compression and Middle Turn Summarization Engine.

Enforces two-end anchor guards (protecting initial intent head and recent error/action tail),
while elastically compressing middle-turn exploration into structured progress summaries.
"""

from __future__ import annotations

import threading
from typing import Callable

from .sandwich_trajectory_types import (
    CompressionResult,
    SandwichPartition,
    TrajectoryCompressionConfig,
)


class SandwichTrajectoryCompressor:
    """Industrial compressor delivering two-end anchor guards and middle trajectory summarization."""

    SUMMARY_TAG: str = "[TRAJECTORY PROGRESS SUMMARY]"

    def __init__(self, config: TrajectoryCompressionConfig | None = None) -> None:
        self.config = config or TrajectoryCompressionConfig()
        self._lock = threading.Lock()

    def estimate_tokens(self, messages: list[dict[str, str]] | tuple[dict[str, str], ...]) -> int:
        """Estimate token consumption using standard ~4 chars per token heuristic."""
        total_chars = sum(len(m.get("content", "")) for m in messages)
        return max(1, total_chars // 4)

    def partition_sandwich(
        self, messages: list[dict[str, str]]
    ) -> SandwichPartition:
        """Partition message sequence into HeadZone, MiddleZone, and TailZone."""
        # Split messages into turns based on 'user' messages (excluding system messages)
        system_msgs: list[dict[str, str]] = []
        turn_blocks: list[list[dict[str, str]]] = []
        current_turn: list[dict[str, str]] = []

        for m in messages:
            if m.get("role") == "system":
                system_msgs.append(m)
                continue

            if m.get("role") == "user":
                if current_turn:
                    turn_blocks.append(current_turn)
                current_turn = [m]
            else:
                if current_turn:
                    current_turn.append(m)
                else:
                    current_turn = [m]

        if current_turn:
            turn_blocks.append(current_turn)

        total_turns = len(turn_blocks)
        head_count = self.config.head_protect_turns
        tail_count = self.config.tail_protect_turns

        # Check if conversation is too short for a middle region
        if total_turns <= (head_count + tail_count):
            return SandwichPartition(
                head_messages=tuple(messages),
                middle_messages=(),
                tail_messages=(),
                head_token_count=self.estimate_tokens(messages),
                middle_token_count=0,
                tail_token_count=0,
                total_token_count=self.estimate_tokens(messages),
            )

        # Assemble HeadZone: system messages + first head_count turns
        head_list: list[dict[str, str]] = list(system_msgs)
        for t_idx in range(head_count):
            head_list.extend(turn_blocks[t_idx])

        # Assemble TailZone: last tail_count turns
        tail_list: list[dict[str, str]] = []
        for t_idx in range(total_turns - tail_count, total_turns):
            tail_list.extend(turn_blocks[t_idx])

        # Assemble MiddleZone: turns between head and tail
        middle_list: list[dict[str, str]] = []
        for t_idx in range(head_count, total_turns - tail_count):
            middle_list.extend(turn_blocks[t_idx])

        head_tokens = self.estimate_tokens(head_list)
        middle_tokens = self.estimate_tokens(middle_list)
        tail_tokens = self.estimate_tokens(tail_list)

        return SandwichPartition(
            head_messages=tuple(head_list),
            middle_messages=tuple(middle_list),
            tail_messages=tuple(tail_list),
            head_token_count=head_tokens,
            middle_token_count=middle_tokens,
            tail_token_count=tail_tokens,
            total_token_count=head_tokens + middle_tokens + tail_tokens,
        )

    def compress_trajectory(
        self,
        messages: list[dict[str, str]],
        custom_summarizer: Callable[[list[dict[str, str]]], str] | None = None,
    ) -> tuple[list[dict[str, str]], CompressionResult]:
        """Perform sandwich compression on messages, protecting head and tail anchors."""
        with self._lock:
            partition = self.partition_sandwich(messages)
            original_tokens = partition.total_token_count

            # If under budget or no middle zone, pass through with zero modification
            if original_tokens <= self.config.target_max_tokens or not partition.middle_messages:
                return list(messages), CompressionResult(
                    is_compressed=False,
                    original_tokens=original_tokens,
                    compacted_tokens=original_tokens,
                    reclaimed_tokens=0,
                    head_preserved_count=len(partition.head_messages),
                    tail_preserved_count=len(partition.tail_messages),
                    middle_absorbed_count=0,
                    summary_inserted=False,
                )

            # Stage 1: Elastic tool output truncation in MiddleZone
            stage1_middle: list[dict[str, str]] = []
            max_tool_chars = self.config.max_tool_output_chars_in_middle

            for m in partition.middle_messages:
                role = m.get("role", "")
                content = m.get("content", "")
                if (role in ("tool", "function") or "tool" in role) and len(content) > max_tool_chars:
                    truncated_content = (
                        content[:max_tool_chars]
                        + f"\n... [Tool output truncated: {len(content) - max_tool_chars} characters trimmed to fit budget] ..."
                    )
                    stage1_middle.append({"role": role, "content": truncated_content})
                else:
                    stage1_middle.append(dict(m))

            candidate_tokens = (
                partition.head_token_count
                + self.estimate_tokens(stage1_middle)
                + partition.tail_token_count
            )

            # If Stage 1 is sufficient to fit under budget, use it
            if candidate_tokens <= self.config.target_max_tokens:
                reconstructed = (
                    list(partition.head_messages)
                    + stage1_middle
                    + list(partition.tail_messages)
                )
                reclaimed = original_tokens - candidate_tokens
                return reconstructed, CompressionResult(
                    is_compressed=True,
                    original_tokens=original_tokens,
                    compacted_tokens=candidate_tokens,
                    reclaimed_tokens=reclaimed,
                    head_preserved_count=len(partition.head_messages),
                    tail_preserved_count=len(partition.tail_messages),
                    middle_absorbed_count=len(partition.middle_messages),
                    summary_inserted=False,
                )

            # Stage 2: Aggregate middle zone into a single progress summary message
            if custom_summarizer is not None:
                summary_text = custom_summarizer(list(partition.middle_messages))
            else:
                summary_text = self._build_default_middle_summary(list(partition.middle_messages))

            summary_message = {
                "role": "user",
                "content": f"{self.SUMMARY_TAG}\n{summary_text}\n[END PROGRESS SUMMARY]",
            }

            reconstructed = (
                list(partition.head_messages)
                + [summary_message]
                + list(partition.tail_messages)
            )

            compacted_tokens = self.estimate_tokens(reconstructed)
            reclaimed = max(0, original_tokens - compacted_tokens)

            return reconstructed, CompressionResult(
                is_compressed=True,
                original_tokens=original_tokens,
                compacted_tokens=compacted_tokens,
                reclaimed_tokens=reclaimed,
                head_preserved_count=len(partition.head_messages),
                tail_preserved_count=len(partition.tail_messages),
                middle_absorbed_count=len(partition.middle_messages),
                summary_inserted=True,
            )

    def _build_default_middle_summary(self, middle_messages: list[dict[str, str]]) -> str:
        """Synthesize a deterministic progress narrative from middle turn actions."""
        tool_count = sum(1 for m in middle_messages if m.get("role") in ("tool", "function"))
        asst_count = sum(1 for m in middle_messages if m.get("role") == "assistant")

        key_snippets: list[str] = []
        for m in middle_messages:
            if m.get("role") == "assistant":
                text = m.get("content", "").strip()
                if text:
                    key_snippets.append(f"• Action: {text[:100]}...")
            elif m.get("role") in ("tool", "function"):
                text = m.get("content", "").strip()
                if "error" in text.lower():
                    key_snippets.append(f"• Encountered note: {text[:100]}...")

        # Keep top 3 milestones to stay strictly under summary token budget
        condensed_snippets = key_snippets[:3]
        snippets_joined = "\n".join(condensed_snippets) if condensed_snippets else "• Intermediate exploration completed."

        return (
            f"Prior intermediate trajectory consisted of {asst_count} reasoning steps and {tool_count} tool executions.\n"
            f"Key observations:\n{snippets_joined}\n"
            f"All intermediate tool explorations have converged; proceed with active tail context."
        )

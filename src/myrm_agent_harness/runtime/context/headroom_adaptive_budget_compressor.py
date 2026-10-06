"""Headroom Adaptive Context Token Budget & Progressive Sliding Window Compressor (Pi Harness v2 Item 27).

Implements adaptive token budgeting and progressive multi-level sliding-window context compaction:
1. Adaptive Token Budget Allocation:
   Dynamically adjusts historical context versus maximum generation tokens according to task phases
   (exploration, planning, implementation, verification) to prevent early token exhaustion.
2. Multi-Level Progressive Sliding-Window Compaction:
   - Level 0: Raw untouched messages when under budget.
   - Level 1: Lightweight tool output folding — replaces verbose tool outputs with structured single-line
     summaries while preserving call metadata and conclusions.
   - Level 2: Semantic batch summarization — synthesizes distant interaction rounds into a unified
     milestone summary when approaching context boundaries (>90%).
3. High-Fidelity Context Unfurling:
   Enables on-demand expansion of folded tool outputs by tool_call_id so critical details are never lost.

[INPUT]
- context_window: int
- current_tokens: int
- phase: TaskPhase
- messages: Sequence[BaseMessage]

[OUTPUT]
- TaskPhase
- CompressionLevel
- AdaptiveBudgetProfile
- FoldedToolRecord
- ProgressiveCompactionResult
- AdaptiveBudgetManager
- ProgressiveSlidingWindowCompactor

[POS]
Harness runtime context layer. Prevents token exhaustion across long-horizon multi-turn execution.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage

from myrm_agent_harness.utils.token_estimation import estimate_message_tokens, estimate_messages_tokens


class TaskPhase(StrEnum):
    """Execution phase defining context-to-generation token ratio."""

    EXPLORATION = "exploration"
    PLANNING = "planning"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"


class CompressionLevel(StrEnum):
    """Progressive levels of context compression."""

    LEVEL_0_RAW = "raw"
    LEVEL_1_FOLD_TOOL = "fold_tool"
    LEVEL_2_SEMANTIC_SUMMARY = "semantic_summary"


@dataclass(slots=True, frozen=True)
class AdaptiveBudgetProfile:
    """Dynamically computed token budget according to task phase."""

    context_window: int
    task_phase: TaskPhase
    target_context_tokens: int
    max_output_tokens: int
    level_1_trigger_tokens: int
    level_2_trigger_tokens: int


@dataclass(slots=True, frozen=True)
class FoldedToolRecord:
    """Historical record of a folded tool output allowing high-fidelity unfurling."""

    tool_call_id: str
    tool_name: str
    raw_output: str
    folded_summary: str
    saved_tokens: int


@dataclass(slots=True, frozen=True)
class ProgressiveCompactionResult:
    """Result of progressive sliding-window compaction pass."""

    compressed_messages: list[BaseMessage]
    level_applied: CompressionLevel
    tokens_before: int
    tokens_after: int
    saved_tokens: int
    folded_tools_count: int


class AdaptiveBudgetManager:
    """Calculates phase-aware token allocation profiles."""

    # Context ratio vs Generation ratio per phase
    _PHASE_RATIOS: ClassVar[dict[TaskPhase, tuple[float, float]]] = {
        TaskPhase.EXPLORATION: (0.85, 0.15),
        TaskPhase.PLANNING: (0.75, 0.25),
        TaskPhase.IMPLEMENTATION: (0.65, 0.35),
        TaskPhase.VERIFICATION: (0.80, 0.20),
    }

    @classmethod
    def calculate_profile(
        cls,
        context_window: int,
        phase: TaskPhase = TaskPhase.EXPLORATION,
        *,
        level_1_ratio: float = 0.80,
        level_2_ratio: float = 0.90,
    ) -> AdaptiveBudgetProfile:
        """Derive token allocation profile dynamically for current phase."""
        ctx_ratio, out_ratio = cls._PHASE_RATIOS.get(phase, (0.75, 0.25))
        target_ctx = int(context_window * ctx_ratio)
        max_out = int(context_window * out_ratio)
        lvl1_trigger = int(target_ctx * level_1_ratio)
        lvl2_trigger = int(target_ctx * level_2_ratio)

        return AdaptiveBudgetProfile(
            context_window=context_window,
            task_phase=phase,
            target_context_tokens=target_ctx,
            max_output_tokens=max_out,
            level_1_trigger_tokens=lvl1_trigger,
            level_2_trigger_tokens=lvl2_trigger,
        )


class ProgressiveSlidingWindowCompactor:
    """Performs multi-level progressive compaction with high-fidelity unfurling."""

    def __init__(self, recent_tail_turns: int = 4) -> None:
        self.recent_tail_turns = recent_tail_turns
        self._unfurl_vault: dict[str, FoldedToolRecord] = {}

    def unfurl_tool_output(self, tool_call_id: str) -> str | None:
        """High-fidelity restoration: retrieves raw output of a previously folded tool call."""
        record = self._unfurl_vault.get(tool_call_id)
        return record.raw_output if record else None

    def compact(
        self,
        messages: Sequence[BaseMessage],
        profile: AdaptiveBudgetProfile,
    ) -> ProgressiveCompactionResult:
        """Run progressive sliding-window compaction against given budget profile."""
        tokens_before = estimate_messages_tokens(messages)

        # Level 0: Below Level 1 trigger threshold -> keep untouched
        if tokens_before <= profile.level_1_trigger_tokens:
            return ProgressiveCompactionResult(
                compressed_messages=list(messages),
                level_applied=CompressionLevel.LEVEL_0_RAW,
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                saved_tokens=0,
                folded_tools_count=0,
            )

        # Split into historical prefix and protected recent tail
        tail_cutoff = max(0, len(messages) - self.recent_tail_turns)
        history_msgs = list(messages[:tail_cutoff])
        protected_tail = list(messages[tail_cutoff:])

        # Level 1: Fold verbose tool outputs in historical prefix
        folded_history: list[BaseMessage] = []
        folded_count = 0

        for msg in history_msgs:
            if isinstance(msg, ToolMessage):
                content_str = str(msg.content)
                call_id = getattr(msg, "tool_call_id", "") or "unknown_call_id"
                tool_name = getattr(msg, "name", "") or "tool"

                # Only fold if verbose (> 150 chars)
                if len(content_str) > 150:
                    first_line = content_str.strip().splitlines()[0] if content_str.strip() else ""
                    folded_marker = f"[FOLDED_OUTPUT id={call_id} tool={tool_name}]: {first_line[:120]}... [Unfurlable]"
                    saved = max(0, estimate_message_tokens(msg) - estimate_message_tokens(ToolMessage(content=folded_marker, tool_call_id=call_id)))

                    self._unfurl_vault[call_id] = FoldedToolRecord(
                        tool_call_id=call_id,
                        tool_name=tool_name,
                        raw_output=content_str,
                        folded_summary=folded_marker,
                        saved_tokens=saved,
                    )
                    folded_history.append(ToolMessage(content=folded_marker, tool_call_id=call_id, name=tool_name))
                    folded_count += 1
                else:
                    folded_history.append(msg)
            else:
                folded_history.append(msg)

        lvl1_messages = folded_history + protected_tail
        lvl1_tokens = estimate_messages_tokens(lvl1_messages)

        # Check if Level 1 brought tokens safely below Level 2 trigger threshold
        if lvl1_tokens <= profile.level_2_trigger_tokens:
            return ProgressiveCompactionResult(
                compressed_messages=lvl1_messages,
                level_applied=CompressionLevel.LEVEL_1_FOLD_TOOL,
                tokens_before=tokens_before,
                tokens_after=lvl1_tokens,
                saved_tokens=tokens_before - lvl1_tokens,
                folded_tools_count=folded_count,
            )

        # Level 2: Still exceeding level 2 threshold -> Synthesize milestone summary for oldest rounds
        # Keep leading system message if present
        system_headers: list[BaseMessage] = []
        summarizable_body: list[BaseMessage] = []

        for msg in folded_history:
            if isinstance(msg, SystemMessage) and not summarizable_body:
                system_headers.append(msg)
            else:
                summarizable_body.append(msg)

        # Build milestone summary block
        summary_lines: list[str] = [
            "<!-- PROGRESSIVE LEVEL 2 SUMMARY: Collapsed historical turns to avoid token exhaustion -->",
        ]
        for msg in summarizable_body:
            role_label = type(msg).__name__.replace("Message", "")
            preview = str(msg.content).strip().replace("\n", " ")[:100]
            summary_lines.append(f"- [{role_label}] {preview}...")
        summary_lines.append("<!-- END PROGRESSIVE SUMMARY -->")

        summary_msg = SystemMessage(content="\n".join(summary_lines))
        lvl2_messages = [*system_headers, summary_msg, *protected_tail]
        lvl2_tokens = estimate_messages_tokens(lvl2_messages)

        return ProgressiveCompactionResult(
            compressed_messages=lvl2_messages,
            level_applied=CompressionLevel.LEVEL_2_SEMANTIC_SUMMARY,
            tokens_before=tokens_before,
            tokens_after=lvl2_tokens,
            saved_tokens=tokens_before - lvl2_tokens,
            folded_tools_count=folded_count,
        )

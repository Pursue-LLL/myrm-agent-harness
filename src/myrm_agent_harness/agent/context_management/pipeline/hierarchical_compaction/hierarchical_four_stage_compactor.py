"""Orchestrates four-stage hierarchical context compaction.

[INPUT]
- agent.context_management.pipeline.hierarchical_compaction.compaction_types::CompactionMetrics,
  CompactionStage, DerivedContextView, HierarchicalCompactionConfig, MessageRole, PipelineMessage,
  TrimmedToolResult (POS: Types and models for compaction.)

[OUTPUT]
- HierarchicalFourStageCompactor: Orchestrates four-stage hierarchical context compaction.

[POS]
Orchestrates four-stage hierarchical context compaction.
"""

# ============================================================================
# HierarchicalFourStageCompactor (Item 154)
# Production-grade 4-stage context compaction pipeline:
# 1. Tool result budget trimming
# 2. Segmented history compaction
# 3. Core assets & pending goals invariant enforcement
# 4. View-level derivation decoupled from disk storage
# ============================================================================

from __future__ import annotations

import logging

from .compaction_types import (
    CompactionMetrics,
    CompactionStage,
    DerivedContextView,
    HierarchicalCompactionConfig,
    MessageRole,
    PipelineMessage,
    TrimmedToolResult,
)

logger = logging.getLogger(__name__)


class HierarchicalFourStageCompactor:
    """Orchestrates four-stage hierarchical context compaction."""

    def __init__(self, config: HierarchicalCompactionConfig | None = None) -> None:
        self.config: HierarchicalCompactionConfig = config or HierarchicalCompactionConfig()

    def _calculate_total_chars(self, messages: list[PipelineMessage]) -> int:
        """Calculates total character count across all messages."""
        return sum(len(m.content) for m in messages)

    def _trim_single_tool_result(
        self,
        message: PipelineMessage,
    ) -> tuple[PipelineMessage, TrimmedToolResult | None]:
        """Trims a single bloated tool result using head/tail retention window."""
        content = message.content
        orig_len = len(content)
        if orig_len <= self.config.tool_result_budget_chars:
            return message.clone(), None

        lines = content.splitlines()
        total_lines = len(lines)
        head_n = self.config.tool_result_head_lines
        tail_n = self.config.tool_result_tail_lines

        if total_lines <= head_n + tail_n:
            # Fallback to character truncation if line count is small but characters are huge
            half = self.config.tool_result_budget_chars // 2
            trimmed_text = (
                f"{content[:half]}\n... [TRUNCATED: {orig_len} chars. "
                f"Restore Hint: {message.tool_name or 'tool'}] ...\n{content[-half:]}"
            )
        else:
            head_lines = lines[:head_n]
            tail_lines = lines[-tail_n:]
            hint = f"Restore Hint: {message.tool_name or 'tool'}"
            trimmed_text = (
                f"{chr(10).join(head_lines)}\n... [TRUNCATED: total {total_lines} lines / {orig_len} chars. {hint}] ...\n"
                f"{chr(10).join(tail_lines)}"
            )

        trimmed_msg = message.clone()
        trimmed_msg.content = trimmed_text

        record = TrimmedToolResult(
            message_id=message.message_id,
            tool_name=message.tool_name or "tool",
            original_chars=orig_len,
            trimmed_chars=len(trimmed_text),
            restore_hint=f"Restore Hint: {message.tool_name or 'tool'}",
        )
        return trimmed_msg, record

    def _stage_1_trim_tool_results(
        self,
        messages: list[PipelineMessage],
    ) -> tuple[list[PipelineMessage], list[TrimmedToolResult]]:
        """Stage 1: Priority tool result budget trimming."""
        derived: list[PipelineMessage] = []
        records: list[TrimmedToolResult] = []

        for m in messages:
            if m.role == MessageRole.TOOL or m.tool_name is not None:
                new_m, record = self._trim_single_tool_result(m)
                derived.append(new_m)
                if record is not None:
                    records.append(record)
            else:
                derived.append(m.clone())

        return derived, records

    def _stage_2_compact_segmented_history(
        self,
        messages: list[PipelineMessage],
    ) -> tuple[list[PipelineMessage], str, int]:
        """Stage 2: Segmented history compaction for early turns."""
        protected_prefix: list[PipelineMessage] = []
        candidate_turns: list[PipelineMessage] = []
        recent_tail: list[PipelineMessage] = []

        # Separate system / pinned / goal messages which are untouchable
        normal_dialogue: list[PipelineMessage] = []
        for m in messages:
            if m.is_system or m.is_goal_state or m.is_pinned or m.role == MessageRole.SYSTEM:
                protected_prefix.append(m.clone())
            else:
                normal_dialogue.append(m)

        # Identify recent turns to protect
        # Each turn is roughly 2 messages (User + Assistant)
        recent_count = self.config.keep_recent_turns * 2
        if len(normal_dialogue) <= recent_count:
            return [m.clone() for m in messages], "", 0

        old_dialogue = normal_dialogue[:-recent_count]
        recent_tail = [m.clone() for m in normal_dialogue[-recent_count:]]

        # Extract structured facts summary from old dialogue
        facts: list[str] = []
        for m in old_dialogue:
            if m.role == MessageRole.USER:
                facts.append(f"• User Directive: {m.content[:80]}...")
            elif m.role == MessageRole.ASSISTANT:
                facts.append(f"• Agent Conclusion: {m.content[:80]}...")

        summary_block = (
            "<compacted_history_summary>\n"
            "### 📜 早期历史对话分段压缩精要：\n"
            f"{chr(10).join(facts[:12])}\n"
            "</compacted_history_summary>"
        )

        summary_msg = PipelineMessage(
            message_id="msg-compacted-summary",
            role=MessageRole.SYSTEM,
            content=summary_block,
            is_system=True,
        )

        compacted_list = [*protected_prefix, summary_msg, *recent_tail]
        compressed_turns = len(old_dialogue) // 2
        return compacted_list, summary_block, compressed_turns

    def _stage_3_enforce_invariants(
        self,
        original_messages: list[PipelineMessage],
        derived_messages: list[PipelineMessage],
    ) -> None:
        """Stage 3: Enforces core assets & pending goals invariant."""
        derived_ids = {m.message_id for m in derived_messages}

        for orig in original_messages:
            if orig.is_system and self.config.protect_system_prompts:
                if orig.message_id not in derived_ids:
                    raise AssertionError(f"System asset invariant violated: {orig.message_id}")
            if orig.is_goal_state and self.config.protect_pending_goals:
                if orig.message_id not in derived_ids:
                    raise AssertionError(f"Pending goal invariant violated: {orig.message_id}")
            if orig.is_pinned:
                if orig.message_id not in derived_ids:
                    raise AssertionError(f"Pinned context invariant violated: {orig.message_id}")

    def compact(self, messages: list[PipelineMessage]) -> DerivedContextView:
        """Executes the four-stage hierarchical context compaction pipeline."""
        initial_chars = self._calculate_total_chars(messages)
        stages_applied: list[CompactionStage] = []
        trimmed_tools_count = 0
        compressed_turns_count = 0
        summary_block: str | None = None

        working_messages = [m.clone() for m in messages]

        # Check if already within budget
        if initial_chars <= self.config.max_context_chars:
            self._stage_3_enforce_invariants(messages, working_messages)
            stages_applied.append(CompactionStage.STAGE_3_CORE_ASSET_PROTECTION)
            stages_applied.append(CompactionStage.STAGE_4_VIEW_DERIVATION)

            metrics = CompactionMetrics(
                initial_chars=initial_chars,
                final_chars=initial_chars,
                chars_saved=0,
                reduction_ratio=0.0,
                stages_applied=stages_applied,
            )
            return DerivedContextView(derived_messages=working_messages, metrics=metrics)

        # Stage 1: Tool result budget trimming
        trimmed_msgs, records = self._stage_1_trim_tool_results(working_messages)
        stages_applied.append(CompactionStage.STAGE_1_TOOL_TRIM)
        trimmed_tools_count = len(records)
        working_messages = trimmed_msgs

        current_chars = self._calculate_total_chars(working_messages)

        # Stage 2: Segmented history compaction if still bloated
        if current_chars > self.config.max_context_chars:
            compacted_msgs, s_block, turns_compressed = self._stage_2_compact_segmented_history(working_messages)
            stages_applied.append(CompactionStage.STAGE_2_SEGMENTED_HISTORY)
            working_messages = compacted_msgs
            summary_block = s_block
            compressed_turns_count = turns_compressed

        # Stage 3: Core assets and pending goals invariant check
        self._stage_3_enforce_invariants(messages, working_messages)
        stages_applied.append(CompactionStage.STAGE_3_CORE_ASSET_PROTECTION)

        # Stage 4: View derivation (memory-only, storage untouched)
        stages_applied.append(CompactionStage.STAGE_4_VIEW_DERIVATION)
        final_chars = self._calculate_total_chars(working_messages)
        chars_saved = max(0, initial_chars - final_chars)
        ratio = (chars_saved / initial_chars) if initial_chars > 0 else 0.0

        metrics = CompactionMetrics(
            initial_chars=initial_chars,
            final_chars=final_chars,
            chars_saved=chars_saved,
            reduction_ratio=ratio,
            stages_applied=stages_applied,
            trimmed_tools_count=trimmed_tools_count,
            compressed_turns_count=compressed_turns_count,
        )

        return DerivedContextView(
            derived_messages=working_messages,
            metrics=metrics,
            summary_block=summary_block,
        )

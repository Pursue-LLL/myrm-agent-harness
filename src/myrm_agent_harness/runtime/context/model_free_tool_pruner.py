"""Model-free deterministic tool result pruner and zero-cost context compactor.

Implements DeepSeek-style compaction-tool-result-pruner: executes pure algorithmic,
zero-LLM-cost pruning on historical read-only tool results, preserves critical error signals,
and maintains recent turn immunity.

[INPUT]
- runtime.context.internal_external_message_pipeline_types::AgentMessage, AgentMessageKind (POS: Type
  definitions for internal/external message separation and context transformation pipeline.)
- runtime.context.model_free_tool_pruner_types::ModelFreeCompactionReport, ModelFreePrunerConfig,
  PruningAuditItem (POS: Type definitions for model-free deterministic tool result pruner and zero-cost
  context compactor.)

[OUTPUT]
- ModelFreeDeterministicToolResultPruner: Performs deterministic zero-cost historical tool output folding
  and token mitigation.

[POS]
Model-free deterministic tool result pruner and zero-cost context compactor.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.internal_external_message_pipeline_types import (
    AgentMessage,
    AgentMessageKind,
)
from myrm_agent_harness.runtime.context.model_free_tool_pruner_types import (
    ModelFreeCompactionReport,
    ModelFreePrunerConfig,
    PruningAuditItem,
)

logger = logging.getLogger(__name__)


class ModelFreeDeterministicToolResultPruner:
    """Performs deterministic zero-cost historical tool output folding and token mitigation."""

    def __init__(self, default_config: ModelFreePrunerConfig | None = None) -> None:
        self._default_config = default_config or ModelFreePrunerConfig()

    def prune_messages(
        self,
        messages: Sequence[AgentMessage],
        config: ModelFreePrunerConfig | None = None,
    ) -> tuple[list[AgentMessage], ModelFreeCompactionReport]:
        """Prune historical tool execution outputs without invoking any external LLM."""
        cfg = config or self._default_config
        pruned_messages: list[AgentMessage] = []
        audit_items: list[PruningAuditItem] = []

        total_scanned = len(messages)
        tools_pruned_count = 0
        original_total_chars = sum(len(m.content) for m in messages)

        # 1. Determine recent immune tool execution messages
        immune_ids: set[str] = set()
        tool_count_from_tail = 0
        for msg in reversed(messages):
            if msg.kind == AgentMessageKind.TOOL_EXECUTION:
                if tool_count_from_tail < cfg.recent_immune_turns:
                    immune_ids.add(msg.message_id)
                    tool_count_from_tail += 1
                else:
                    break

        # 2. Iterate and apply deterministic pruning
        for msg in messages:
            if msg.kind != AgentMessageKind.TOOL_EXECUTION:
                pruned_messages.append(msg)
                continue

            tool_name = msg.tool_name or "tool"
            orig_len = len(msg.content)

            # Immune recent window check
            if msg.message_id in immune_ids:
                pruned_messages.append(msg)
                audit_items.append(
                    PruningAuditItem(
                        message_id=msg.message_id,
                        tool_name=tool_name,
                        original_chars=orig_len,
                        pruned_chars=orig_len,
                        was_error=msg.is_error,
                        strategy_applied="skipped_immune",
                    )
                )
                continue

            # Small output check
            if orig_len < cfg.min_prune_char_threshold:
                pruned_messages.append(msg)
                audit_items.append(
                    PruningAuditItem(
                        message_id=msg.message_id,
                        tool_name=tool_name,
                        original_chars=orig_len,
                        pruned_chars=orig_len,
                        was_error=msg.is_error,
                        strategy_applied="skipped_small",
                    )
                )
                continue

            # Error Signal Preservation
            if msg.is_error:
                lines = msg.content.splitlines()
                if len(lines) <= cfg.error_tail_lines:
                    pruned_messages.append(msg)
                    audit_items.append(
                        PruningAuditItem(
                            message_id=msg.message_id,
                            tool_name=tool_name,
                            original_chars=orig_len,
                            pruned_chars=orig_len,
                            was_error=True,
                            strategy_applied="skipped_small",
                        )
                    )
                else:
                    tail_lines = lines[-cfg.error_tail_lines:]
                    folded_count = len(lines) - len(tail_lines)
                    new_content = (
                        f"[Tool '{tool_name}' failed: {folded_count} verbose lines folded; "
                        f"preserving last {len(tail_lines)} error lines]\n"
                        + "\n".join(tail_lines)
                    )
                    compacted_msg = self._replace_message_content(msg, new_content)
                    pruned_messages.append(compacted_msg)
                    tools_pruned_count += 1
                    audit_items.append(
                        PruningAuditItem(
                            message_id=msg.message_id,
                            tool_name=tool_name,
                            original_chars=orig_len,
                            pruned_chars=len(new_content),
                            was_error=True,
                            strategy_applied="retained_error_tail",
                        )
                    )
                continue

            # Read-only or historical successful output folding
            lines_count = len(msg.content.splitlines())
            new_content = (
                f"[Tool '{tool_name}' succeeded: {lines_count} lines folded "
                f"to preserve context budget]"
            )
            compacted_msg = self._replace_message_content(msg, new_content)
            pruned_messages.append(compacted_msg)
            tools_pruned_count += 1
            audit_items.append(
                PruningAuditItem(
                    message_id=msg.message_id,
                    tool_name=tool_name,
                    original_chars=orig_len,
                    pruned_chars=len(new_content),
                    was_error=False,
                    strategy_applied="folded_readonly",
                )
            )

        compacted_total_chars = sum(len(m.content) for m in pruned_messages)
        chars_freed = max(0, original_total_chars - compacted_total_chars)
        tokens_freed = max(1, chars_freed // 4) if chars_freed > 0 else 0
        savings_ratio = (
            round(chars_freed / original_total_chars, 3)
            if original_total_chars > 0
            else 0.0
        )

        report = ModelFreeCompactionReport(
            total_messages_scanned=total_scanned,
            tools_pruned_count=tools_pruned_count,
            original_total_chars=original_total_chars,
            compacted_total_chars=compacted_total_chars,
            chars_freed=chars_freed,
            tokens_freed_estimate=tokens_freed,
            savings_ratio=savings_ratio,
            audit_items=audit_items,
        )

        logger.debug(
            "Deterministic pruning completed: %d tools pruned, %d chars freed (savings=%.1f%%)",
            tools_pruned_count,
            chars_freed,
            savings_ratio * 100.0,
        )

        return pruned_messages, report

    def _replace_message_content(self, msg: AgentMessage, new_content: str) -> AgentMessage:
        """Create a new AgentMessage with updated content while preserving all identity metadata."""
        return AgentMessage(
            message_id=msg.message_id,
            kind=msg.kind,
            content=new_content,
            timestamp=msg.timestamp,
            metadata=msg.metadata,
            tool_call_id=msg.tool_call_id,
            tool_name=msg.tool_name,
            tool_arguments=msg.tool_arguments,
            is_error=msg.is_error,
            is_streaming_incomplete=msg.is_streaming_incomplete,
            reasoning_content=msg.reasoning_content,
        )

"""Internal/external message separation and context transformation pipeline.

Implements transformContext() middleware for progressive compression and
convertToLlm() protocol adapter to enforce zero internal metadata leakage to external LLMs.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.internal_external_message_pipeline_types import (
    AgentMessage,
    AgentMessageKind,
    LlmMessage,
    LlmToolCall,
    TransformPipelineMetrics,
    TransformPipelineOptions,
)

logger = logging.getLogger(__name__)


class InternalExternalMessagePipeline:
    """Orchestrates message separation, progressive compression, and LLM protocol conversion."""

    def __init__(self, default_options: TransformPipelineOptions | None = None) -> None:
        self._default_options = default_options or TransformPipelineOptions()

    def transform_context(
        self,
        messages: Sequence[AgentMessage],
        options: TransformPipelineOptions | None = None,
    ) -> list[AgentMessage]:
        """Perform progressive in-memory compression and sanitization on internal AgentMessages.

        - Prunes incomplete streaming messages if configured
        - Truncates oversized tool execution output while preserving head and tail diagnostic context
        """
        opts = options or self._default_options
        transformed: list[AgentMessage] = []

        for msg in messages:
            if opts.drop_incomplete_streaming and msg.is_streaming_incomplete:
                logger.debug("Dropping incomplete streaming message: %s", msg.message_id)
                continue

            if msg.kind == AgentMessageKind.TOOL_EXECUTION:
                processed_msg = self._truncate_tool_output_if_needed(msg, opts)
                transformed.append(processed_msg)
            else:
                transformed.append(msg)

        return transformed

    def convert_to_llm(
        self,
        messages: Sequence[AgentMessage],
        options: TransformPipelineOptions | None = None,
    ) -> tuple[list[LlmMessage], TransformPipelineMetrics]:
        """Convert sanitized internal AgentMessages into external LLM wire protocol messages.

        Enforces strict physical isolation: UI metadata, config mutations, branch markers,
        and human approval gates are pruned to prevent context poisoning and token leakage.
        """
        opts = options or self._default_options
        llm_messages: list[LlmMessage] = []

        input_count = len(messages)
        pruned_meta_count = 0
        dropped_incomplete_count = 0
        saved_chars = 0

        for msg in messages:
            if opts.drop_incomplete_streaming and msg.is_streaming_incomplete:
                dropped_incomplete_count += 1
                saved_chars += len(msg.content)
                continue

            if msg.kind == AgentMessageKind.USER:
                llm_messages.append(LlmMessage(role="user", content=msg.content))

            elif msg.kind == AgentMessageKind.ASSISTANT:
                tool_calls: list[LlmToolCall] | None = None
                if msg.tool_call_id and msg.tool_name:
                    tool_calls = [
                        LlmToolCall(
                            id=msg.tool_call_id,
                            name=msg.tool_name,
                            arguments=msg.tool_arguments or "{}",
                        )
                    ]
                llm_messages.append(
                    LlmMessage(
                        role="assistant",
                        content=msg.content,
                        tool_calls=tool_calls,
                    )
                )

            elif msg.kind == AgentMessageKind.TOOL_EXECUTION:
                llm_messages.append(
                    LlmMessage(
                        role="tool",
                        content=msg.content,
                        tool_call_id=msg.tool_call_id,
                        name=msg.tool_name,
                    )
                )

            elif msg.kind == AgentMessageKind.SYSTEM_NOTIFICATION:
                if opts.allow_system_notifications:
                    llm_messages.append(
                        LlmMessage(
                            role="system",
                            content=f"[System Notification] {msg.content}",
                        )
                    )
                else:
                    pruned_meta_count += 1
                    saved_chars += len(msg.content)

            elif msg.kind in (
                AgentMessageKind.CONFIG_MUTATION,
                AgentMessageKind.BRANCH_MARKER,
                AgentMessageKind.HUMAN_APPROVAL_GATE,
            ):
                # Pure internal runtime metadata - never forwarded to LLM
                pruned_meta_count += 1
                saved_chars += len(msg.content)

        metrics = TransformPipelineMetrics(
            input_internal_count=input_count,
            output_llm_count=len(llm_messages),
            pruned_meta_events_count=pruned_meta_count,
            dropped_incomplete_count=dropped_incomplete_count,
            truncated_tool_chars=0,
            tokens_saved_estimate=max(1, saved_chars // 4) if saved_chars > 0 else 0,
        )

        return llm_messages, metrics

    def execute_pipeline(
        self,
        messages: Sequence[AgentMessage],
        options: TransformPipelineOptions | None = None,
    ) -> tuple[list[LlmMessage], TransformPipelineMetrics]:
        """Execute end-to-end context transformation and protocol conversion."""
        opts = options or self._default_options

        # 1. Progressive transformation
        transformed = self.transform_context(messages, opts)

        # Calculate truncated characters
        truncated_tool_chars = 0
        orig_tool_lens = {
            m.message_id: len(m.content)
            for m in messages
            if m.kind == AgentMessageKind.TOOL_EXECUTION
        }
        for t_msg in transformed:
            if t_msg.kind == AgentMessageKind.TOOL_EXECUTION:
                orig_len = orig_tool_lens.get(t_msg.message_id, len(t_msg.content))
                if orig_len > len(t_msg.content):
                    truncated_tool_chars += orig_len - len(t_msg.content)

        # 2. Wire protocol conversion
        llm_messages, base_metrics = self.convert_to_llm(transformed, opts)

        total_saved_chars = (
            base_metrics.tokens_saved_estimate * 4 + truncated_tool_chars
        )
        total_tokens_saved = max(1, total_saved_chars // 4) if total_saved_chars > 0 else 0

        final_metrics = TransformPipelineMetrics(
            input_internal_count=len(messages),
            output_llm_count=len(llm_messages),
            pruned_meta_events_count=base_metrics.pruned_meta_events_count,
            dropped_incomplete_count=(
                len(messages) - len(transformed)
                if opts.drop_incomplete_streaming
                else 0
            ),
            truncated_tool_chars=truncated_tool_chars,
            tokens_saved_estimate=total_tokens_saved,
        )

        return llm_messages, final_metrics

    def _truncate_tool_output_if_needed(
        self, msg: AgentMessage, opts: TransformPipelineOptions
    ) -> AgentMessage:
        """Truncate oversized tool output while preserving diagnostic head and tail."""
        if len(msg.content) <= opts.max_tool_output_chars:
            return msg

        head_len = int(opts.max_tool_output_chars * opts.truncate_head_ratio)
        tail_len = int(opts.max_tool_output_chars * opts.truncate_tail_ratio)

        if head_len + tail_len >= len(msg.content):
            return msg

        head = msg.content[:head_len]
        tail = msg.content[-tail_len:] if tail_len > 0 else ""
        omitted = len(msg.content) - (head_len + tail_len)

        collapsed_content = (
            f"{head}\n\n"
            f"... [Output truncated: {omitted} chars omitted to preserve context budget] ...\n\n"
            f"{tail}"
        )

        return AgentMessage(
            message_id=msg.message_id,
            kind=msg.kind,
            content=collapsed_content,
            timestamp=msg.timestamp,
            metadata=msg.metadata,
            tool_call_id=msg.tool_call_id,
            tool_name=msg.tool_name,
            tool_arguments=msg.tool_arguments,
            is_error=msg.is_error,
            is_streaming_incomplete=msg.is_streaming_incomplete,
            reasoning_content=msg.reasoning_content,
        )

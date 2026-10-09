"""Projector mapping conversation history to discrete provider content blocks.

[INPUT]
- lookback_prune_types: ContentBlockKind, ProjectedContentBlock.

[OUTPUT]
- ProviderBlockProjector: Simulates the provider request converter (e.g. Anthropic),
  faithfully projecting messages into individual content blocks to accurately count lookback positions.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.lookback_aligned_prune
- Module: provider_block_projector.py
"""

from typing import Mapping, Sequence

from myrm_agent_harness.agent.context_management.lookback_aligned_prune.lookback_prune_types import (
    ContentBlockKind,
    ProjectedContentBlock,
)


class ProviderBlockProjector:
    """Projects conversation messages into provider-aligned content blocks for position counting."""

    def project_messages(
        self,
        messages: Sequence[Mapping[str, str]],
    ) -> Sequence[ProjectedContentBlock]:
        """Projects a sequence of message dicts into discrete LLM-emitted content blocks.

        Args:
            messages: List of message mappings containing 'role', 'content', and optional tool keys.

        Returns:
            Tuple of ProjectedContentBlock instances reflecting the exact payload shapes sent upstream.
        """
        projected: list[ProjectedContentBlock] = []

        for msg_idx, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            tool_kind = msg.get("tool_name")
            has_image = msg.get("has_image", "false").lower() == "true"
            has_file = msg.get("has_file_ref", "false").lower() == "true"

            # 1. Tool message result
            if role == "tool" or tool_kind is not None:
                approx_tokens = max(1, len(content) // 4)
                projected.append(
                    ProjectedContentBlock(
                        message_index=msg_idx,
                        block_kind=ContentBlockKind.TOOL_RESULT,
                        token_count=approx_tokens,
                        identifier=tool_kind,
                        is_prunable_tool_output=True,
                    )
                )
                continue

            # 2. Assistant message potentially containing text and tool calls
            if role == "assistant":
                tool_calls_raw = msg.get("tool_calls", "")
                if content:
                    projected.append(
                        ProjectedContentBlock(
                            message_index=msg_idx,
                            block_kind=ContentBlockKind.TEXT,
                            token_count=max(1, len(content) // 4),
                            identifier=None,
                            is_prunable_tool_output=False,
                        )
                    )
                if tool_calls_raw:
                    # Each emitted tool_use is a distinct block in Anthropic/OpenAI APIs
                    calls = [c.strip() for c in tool_calls_raw.split(",") if c.strip()]
                    for call_sig in calls:
                        projected.append(
                            ProjectedContentBlock(
                                message_index=msg_idx,
                                block_kind=ContentBlockKind.TOOL_USE,
                                token_count=50,
                                identifier=call_sig,
                                is_prunable_tool_output=False,
                            )
                        )
                continue

            # 3. User message with optional image splits and file references
            if has_image:
                projected.append(
                    ProjectedContentBlock(
                        message_index=msg_idx,
                        block_kind=ContentBlockKind.IMAGE,
                        token_count=1600,
                        identifier="attached_image",
                        is_prunable_tool_output=False,
                    )
                )

            if has_file:
                projected.append(
                    ProjectedContentBlock(
                        message_index=msg_idx,
                        block_kind=ContentBlockKind.FILE_REFERENCE,
                        token_count=200,
                        identifier="file_mention",
                        is_prunable_tool_output=False,
                    )
                )

            # Normal text block for user
            projected.append(
                ProjectedContentBlock(
                    message_index=msg_idx,
                    block_kind=ContentBlockKind.TEXT,
                    token_count=max(1, len(content) // 4),
                    identifier=None,
                    is_prunable_tool_output=False,
                )
            )

        return tuple(projected)

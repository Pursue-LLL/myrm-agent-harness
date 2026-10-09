"""Trailing bloated tool message clipper for summary overflow mitigation.

[INPUT]
- overflow_clip_types: ClipStrategyKind, OverflowClipAction, OverflowClipOutcome,
  SummaryOverflowClipConfig.

[OUTPUT]
- TailMessageClipper: Slices oversized read_file outputs and replaces bloated tool results
  with lightweight storage stubs to strictly reduce context size for summarizer retries.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.summary_overflow_clip
- Module: tail_message_clipper.py
"""

from typing import Dict, List, Mapping, Sequence

from myrm_agent_harness.agent.context_management.summary_overflow_clip.overflow_clip_types import (
    ClipStrategyKind,
    OverflowClipAction,
    OverflowClipOutcome,
    SummaryOverflowClipConfig,
)


class TailMessageClipper:
    """Clips trailing bloated tool outputs to eliminate context overflow during auxiliary summary calls."""

    def __init__(self, config: SummaryOverflowClipConfig) -> None:
        self._config = config

    def clip_trailing_tool_overflow(
        self,
        messages: Sequence[Mapping[str, str]],
    ) -> OverflowClipOutcome:
        """Inspects and compacts trailing tool messages to strictly shrink input tokens.

        Args:
            messages: Full conversation turns intended for the summarization LLM call.

        Returns:
            OverflowClipOutcome containing transformed messages and token delta diagnostics.
        """
        clipped_list: List[Dict[str, str]] = [dict(m) for m in messages]
        actions: List[OverflowClipAction] = []
        total_tokens_saved = 0

        # Scan backwards to identify and clip trailing bloated tool outputs first
        for idx in range(len(clipped_list) - 1, -1, -1):
            msg = clipped_list[idx]
            role = msg.get("role", "user")
            content = msg.get("content", "")
            tool_name = msg.get("tool_name", "")

            # Only target tool responses with substantial content length
            if (role == "tool" or bool(tool_name)) and len(content) > self._config.tool_stub_max_chars:
                orig_len = len(content)

                if self._is_read_file_tool(tool_name):
                    # 1. Read file tool: head-slice strategy (retain first N lines)
                    new_content = self._slice_read_file_content(content)
                    strategy = ClipStrategyKind.READ_FILE_HEAD_SLICE
                else:
                    # 2. General tool result: replace with concise stub
                    new_content = (
                        f"[Tool '{tool_name or 'unnamed'}' output offloaded to storage stub "
                        f"due to summary context overflow. Original size: {orig_len} chars.]"
                    )
                    strategy = ClipStrategyKind.OFFLOAD_STUB_REPLACE

                clipped_len = len(new_content)
                chars_saved = max(0, orig_len - clipped_len)
                tokens_saved = max(1, chars_saved // 4)

                msg["content"] = new_content
                total_tokens_saved += tokens_saved

                actions.append(
                    OverflowClipAction(
                        message_index=idx,
                        tool_name=tool_name or None,
                        strategy_applied=strategy,
                        original_characters=orig_len,
                        clipped_characters=clipped_len,
                        estimated_saved_tokens=tokens_saved,
                    )
                )

        is_strictly_reduced = total_tokens_saved >= self._config.min_tokens_saved_to_justify_retry

        diag = (
            f"Clipped {len(actions)} bloated tool message(s), "
            f"saving ~{total_tokens_saved} tokens across summarizer input."
        )

        return OverflowClipOutcome(
            total_messages_clipped=len(actions),
            total_tokens_saved=total_tokens_saved,
            is_strictly_reduced=is_strictly_reduced,
            actions=tuple(actions),
            clipped_messages=tuple(clipped_list),
            diagnostic_summary=diag,
        )

    def _is_read_file_tool(self, tool_name: str) -> bool:
        clean_name = tool_name.lower().strip()
        return any(ident in clean_name for ident in self._config.read_file_tool_identifiers)

    def _slice_read_file_content(self, raw_content: str) -> str:
        lines = raw_content.splitlines()
        max_head = self._config.read_file_max_head_lines
        if len(lines) <= max_head:
            return raw_content

        retained = lines[:max_head]
        omitted = len(lines) - max_head
        retained.append(
            f"\n[... head-sliced: {omitted} trailing lines omitted due to summary context overflow ...]"
        )
        return "\n".join(retained)

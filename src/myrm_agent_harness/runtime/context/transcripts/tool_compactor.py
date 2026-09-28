"""Two-stage tool output compactor for preserving context window capacity during resume.

[INPUT]
- .types::CanonicalToolCall

[OUTPUT]
- compact_tool_output: In-place or copy-based bounded reduction of massive outputs.
- ToolOutputCompactor: Configurable boundary compactor utility.

[POS]
runtime/context/transcripts/tool_compactor.py
Context-protective bounded reducer preventing token explosion on imported sessions.
"""

from __future__ import annotations

from .types import CanonicalToolCall

_DEFAULT_COMPACTION_THRESHOLD_BYTES = 2048
_HEAD_LINES_LIMIT = 25
_TAIL_LINES_LIMIT = 15


class ToolOutputCompactor:
    """Configurable two-stage bounded compactor for tool output text."""

    def __init__(
        self,
        threshold_bytes: int = _DEFAULT_COMPACTION_THRESHOLD_BYTES,
        head_lines: int = _HEAD_LINES_LIMIT,
        tail_lines: int = _TAIL_LINES_LIMIT,
    ) -> None:
        self._threshold_bytes = threshold_bytes
        self._head_lines = head_lines
        self._tail_lines = tail_lines

    def compact(self, tool_call: CanonicalToolCall) -> CanonicalToolCall:
        """Return a compacted CanonicalToolCall if output exceeds threshold."""
        raw_output = tool_call.output
        if raw_output is None:
            return tool_call

        output_bytes_len = len(raw_output.encode("utf-8", errors="replace"))
        if output_bytes_len <= self._threshold_bytes:
            return tool_call

        lines = raw_output.splitlines(keepends=True)
        if len(lines) <= (self._head_lines + self._tail_lines + 2):
            # Short line count but large lines: truncate character-wise
            truncated_body = raw_output[:1024] + f"\n\n... [truncated {output_bytes_len - 1536} bytes] ...\n\n" + raw_output[-512:]
            return CanonicalToolCall(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                arguments=tool_call.arguments,
                output=truncated_body,
                exit_code=tool_call.exit_code,
                is_error=tool_call.is_error,
                compacted=True,
                original_size_bytes=output_bytes_len,
            )

        head_part = "".join(lines[: self._head_lines])
        tail_part = "".join(lines[-self._tail_lines :])
        omitted_lines = len(lines) - self._head_lines - self._tail_lines
        separator = f"\n... [omitted {omitted_lines} lines / {output_bytes_len} bytes total for context efficiency] ...\n"

        compacted_output = f"{head_part}{separator}{tail_part}"
        return CanonicalToolCall(
            call_id=tool_call.call_id,
            tool_name=tool_call.tool_name,
            arguments=tool_call.arguments,
            output=compacted_output,
            exit_code=tool_call.exit_code,
            is_error=tool_call.is_error,
            compacted=True,
            original_size_bytes=output_bytes_len,
        )


def compact_tool_output(tool_call: CanonicalToolCall) -> CanonicalToolCall:
    """Convenience functional helper using default compaction thresholds."""
    return ToolOutputCompactor().compact(tool_call)

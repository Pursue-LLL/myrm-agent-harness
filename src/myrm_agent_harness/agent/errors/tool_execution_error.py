"""Unified tool execution error with structured diagnostics.

Provides base class for all tool execution errors with:
- Execution phase tracking (validation/execution/cleanup)
- Command context
- Intelligent output truncation (head + tail preview)
- UTF-8 safe character-level truncation

[INPUT]
- (none)

[OUTPUT]
- ExecutionPhase: Execution phase for diagnostic context.
- ToolExecutionError: Tool execution failed.

[POS]
Unified tool execution error with structured diagnostics.
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionPhase(StrEnum):
    """Execution phase for diagnostic context."""

    VALIDATION = "validation"
    EXECUTION = "execution"
    CLEANUP = "cleanup"


class ToolExecutionError(Exception):
    """Base class for all tool execution errors with structured diagnostics.

    Provides unified error handling across all tools (bash, HTTP, LLM, file ops, browser)
    with detailed execution context and intelligently truncated output.
    """

    PREVIEW_CHAR_LIMIT = 160

    def __init__(
        self,
        message: str,
        *,
        phase: ExecutionPhase,
        tool_name: str,
        command: str,
        stdout: str = "",
        stderr: str = "",
        error_hint: str = "",
        error_category: str = "UNKNOWN",
        metadata: dict[str, object] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.phase = phase
        self.tool_name = tool_name
        self.command = command
        self.stdout_preview = self._smart_truncate(stdout, self.PREVIEW_CHAR_LIMIT)
        self.stderr_preview = self._smart_truncate(stderr, self.PREVIEW_CHAR_LIMIT)
        self.error_hint = error_hint
        self.error_category = error_category
        self.metadata = metadata or {}

    @staticmethod
    def _smart_truncate(text: str, limit: int) -> str:
        """Intelligent truncation: preserve head + tail, ellipsize middle.

        UTF-8 safe character-level truncation to avoid breaking multi-byte characters.
        Preserves first 80 chars and last 80 chars when text exceeds limit.

        Examples:
            "short" -> "short"
            "very long text..." (200 chars) -> "very long... (80 chars omitted) ...tail"
        """
        if not text:
            return "(empty)"

        if len(text) <= limit:
            return text

        half = limit // 2
        head = text[:half]
        tail = text[-half:]
        omitted = len(text) - limit

        return f"{head}... ({omitted} chars omitted) ...{tail}"

    def format_diagnostic(self) -> str:
        """Generate structured diagnostic report for debugging.

        Returns formatted multi-line string with all execution context.
        """
        lines = [
            "Tool Execution Error",
            "=" * 50,
            f"Tool:     {self.tool_name}",
            f"Phase:    {self.phase.value}",
            f"Category: {self.error_category}",
            f"Command:  {self.command}",
            "",
            "Stdout Preview:",
            f"  {self.stdout_preview}",
            "",
            "Stderr Preview:",
            f"  {self.stderr_preview}",
        ]

        if self.error_hint:
            lines.extend(["", f"Hint: {self.error_hint}"])

        if self.metadata:
            lines.extend(["", f"Metadata: {self.metadata}"])

        lines.append("=" * 50)
        return "\n".join(lines)


__all__ = ["ExecutionPhase", "ToolExecutionError"]

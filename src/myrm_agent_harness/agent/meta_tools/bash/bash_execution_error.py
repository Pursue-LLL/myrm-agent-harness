"""Structured bash execution error with diagnostic previews.

[INPUT]
- None (stdlib only)

[OUTPUT]
- BashExecutionError: Exception with phase/category/hint and stdout/stderr previews

[POS]
Shared error type for BashExecutor mixins and bash_code_execute_tool error surfacing.
"""

from __future__ import annotations


class BashExecutionError(Exception):
    """Bash execution error with structured diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        error_hint: str | None = None,
        error_category: str | None = None,
        phase: str | None = None,
        command: str = "",
        stdout: str = "",
        stderr: str = "",
    ):
        super().__init__(message)
        self.error_hint = error_hint
        self.error_category = error_category
        self.phase = phase
        self.command = command
        self.stdout_preview = self._smart_truncate(stdout, 160)
        self.stderr_preview = self._smart_truncate(stderr, 160)

    @staticmethod
    def _smart_truncate(text: str, limit: int) -> str:
        """Smart truncation: preserve head + tail."""
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
        """Generate structured diagnostic report."""
        if not self.phase:
            return str(self)

        lines = [
            "Bash Execution Error",
            "=" * 50,
            f"Phase:    {self.phase}",
            f"Category: {self.error_category or 'UNKNOWN'}",
            f"Command:  {self.command}",
            "",
            "Stdout Preview:",
            f" {self.stdout_preview}",
            "",
            "Stderr Preview:",
            f" {self.stderr_preview}",
        ]

        if self.error_hint:
            lines.extend(["", f"Hint: {self.error_hint}"])

        lines.append("=" * 50)
        return "\n".join(lines)

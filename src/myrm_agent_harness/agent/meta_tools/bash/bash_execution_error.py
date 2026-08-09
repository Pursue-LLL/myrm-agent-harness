"""Structured bash execution error with eviction references.

[INPUT]
- None (stdlib only)

[OUTPUT]
- BashExecutionError: Exception with phase/category/hint and stdout/stderr eviction
  references for failure-path large-output persistence.

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
        stdout_evicted_ref: str | None = None,
        stdout_evicted_stored_chars: int | None = None,
        stdout_evicted_total_lines: int | None = None,
        stdout_evicted_storage_truncated: bool = False,
        stderr_evicted_ref: str | None = None,
        stderr_evicted_stored_chars: int | None = None,
        stderr_evicted_total_lines: int | None = None,
        stderr_evicted_storage_truncated: bool = False,
    ):
        super().__init__(message)
        self.error_hint = error_hint
        self.error_category = error_category
        self.phase = phase
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        self.stdout_evicted_ref = stdout_evicted_ref
        self.stdout_evicted_stored_chars = stdout_evicted_stored_chars
        self.stdout_evicted_total_lines = stdout_evicted_total_lines
        self.stdout_evicted_storage_truncated = stdout_evicted_storage_truncated
        self.stderr_evicted_ref = stderr_evicted_ref
        self.stderr_evicted_stored_chars = stderr_evicted_stored_chars
        self.stderr_evicted_total_lines = stderr_evicted_total_lines
        self.stderr_evicted_storage_truncated = stderr_evicted_storage_truncated

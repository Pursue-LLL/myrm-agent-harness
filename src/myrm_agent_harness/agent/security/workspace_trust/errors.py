"""Workspace trust gate errors.

[INPUT]
- None (leaf error type with no internal dependencies)

[OUTPUT]
- WorkspaceTrustBlockedError: RuntimeError subclass carrying a `.reason` attribute

[POS]
Error contract of the workspace_trust gate. Callers distinguish policy blocks from
unexpected runtime faults by catching this type, so the class stays I/O-free and
dependency-free to remain importable from every gate call site.
"""

from __future__ import annotations


class WorkspaceTrustBlockedError(RuntimeError):
    """Raised when a side-channel action is blocked for an untrusted workspace."""

    def __init__(self, message: str, *, reason: str = "workspace_not_trusted") -> None:
        super().__init__(message)
        self.reason = reason

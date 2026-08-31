"""Workspace trust gate errors."""

from __future__ import annotations


class WorkspaceTrustBlockedError(RuntimeError):
    """Raised when a side-channel action is blocked for an untrusted workspace."""

    def __init__(self, message: str, *, reason: str = "workspace_not_trusted") -> None:
        super().__init__(message)
        self.reason = reason

"""Workspace trust lookup protocol for server-side registry injection."""

from __future__ import annotations

from typing import Protocol

from .types import WorkspaceTrustLevel


class WorkspaceTrustLookup(Protocol):
    """Resolve trust level for a canonical workspace path."""

    def normalize_path(self, raw_path: str) -> str:
        """Return canonical absolute path or empty string when invalid."""
        ...

    def get_level(self, canonical_path: str) -> WorkspaceTrustLevel | None:
        """Return stored level or None when the path has no decision yet."""
        ...

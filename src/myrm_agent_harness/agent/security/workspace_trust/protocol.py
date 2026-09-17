"""Workspace trust lookup protocol for server-side registry injection.

[INPUT]
- raw_path: str (un-normalized path supplied by a client)
- canonical_path: str (normalized absolute path used as registry key)

[OUTPUT]
- WorkspaceTrustLookup: typing.Protocol declaring normalize_path and get_level

[POS]
Dependency-inversion seam of the workspace_trust gate. The harness declares only the
protocol, so it never imports server persistence code; the server supplies the concrete
registry implementation. get_level returning None means "no decision yet".
"""

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

"""Workspace trust lookup protocol for server-side registry injection.

[INPUT]
- typing::Protocol (POS: Python 结构化子类型协议标准库)
- agent.security.workspace_trust.types::WorkspaceTrustLevel
  (POS: 工作区信任级别类型)

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

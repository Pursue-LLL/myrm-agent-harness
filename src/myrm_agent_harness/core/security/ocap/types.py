"""Object-Capability (OCap) core data types and contracts.

[INPUT]
- (none - foundational security definitions)

[OUTPUT]
- CapabilityAction: Strongly typed permission action enum
- ResourceScope: Immutable resource scope containing paths, domains, and MCP tools
- CapabilityHandle: Cryptographically signed, unforgeable capability token
- AttenuationError: Base error for unauthorized permission elevation attempts
- CapabilityDeniedError: Raised when an operation violates capability constraints

[POS]
Foundational data types for the zero-trust Object-Capability delegation mesh.
Guarantees immutability, type safety, and zero ambient authority.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class CapabilityAction(StrEnum):
    """Permitted operation action types within a capability scope."""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    EGRESS = "egress"
    MCP = "mcp"


@dataclass(frozen=True)
class ResourceScope:
    """Immutable resource boundaries granted to an agent."""

    paths: tuple[str, ...] = field(default_factory=tuple)
    domains: tuple[str, ...] = field(default_factory=tuple)
    mcp_tools: tuple[str, ...] = field(default_factory=tuple)

    def is_unrestricted(self) -> bool:
        """Return True if scope imposes no boundaries (root authority)."""
        return not self.paths and not self.domains and not self.mcp_tools


@dataclass(frozen=True)
class CapabilityHandle:
    """Cryptographically signed, unforgeable capability token."""

    handle_id: str
    issuer_id: str
    subject_id: str
    scope: ResourceScope
    actions: frozenset[CapabilityAction]
    issued_at: float
    expires_at: float
    parent_handle_id: str | None = None
    signature: str = ""

    def is_expired(self, current_time: float | None = None) -> bool:
        """Check if capability handle has expired based on monotonic clock."""
        now = time.monotonic() if current_time is None else current_time
        return now >= self.expires_at

    def remaining_ttl(self, current_time: float | None = None) -> float:
        """Return remaining seconds of validity using monotonic clock."""
        now = time.monotonic() if current_time is None else current_time
        return max(0.0, self.expires_at - now)


class AttenuationError(Exception):
    """Raised when an attenuated capability attempts illegal permission elevation."""


class CapabilityDeniedError(PermissionError):
    """Raised when an operation is physically blocked due to missing or invalid capability."""

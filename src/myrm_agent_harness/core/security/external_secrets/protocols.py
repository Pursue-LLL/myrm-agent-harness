"""Protocols and interfaces for external secret reference resolution.

[INPUT]
- None (standard library only)

[OUTPUT]
- ExternalSecretResolver: Protocol for resolving external vault URIs (op://, bw://, bws://)
- ResolverHealth: Dataclass capturing resolver reachability status and latency

[POS]
Harness core security layer interface. Defines the contract for zero-plaintext
dynamic resolution of external password managers (1Password, Bitwarden).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ResolverHealth:
    """Reachability and health status for an external secret source."""

    scheme: str
    available: bool
    latency_ms: float | None = None
    error_message: str | None = None


@runtime_checkable
class ExternalSecretResolver(Protocol):
    """Protocol for resolving and invalidating external vault secret references."""

    def is_supported(self, reference: str) -> bool:
        """Check whether this resolver handles the given secret reference URI."""
        ...

    def resolve(self, reference: str, force_refresh: bool = False) -> str:
        """Resolve an external secret reference to its plaintext value in memory.

        Args:
            reference: URI reference string (e.g. 'op://Vault/OpenAI/credential').
            force_refresh: When True, bypasses local memory cache and refetches.

        Returns:
            The resolved plaintext secret value.
        """
        ...

    def invalidate(self, reference: str) -> None:
        """Evict the cached value for the given reference (used on 401/403)."""
        ...

    def probe(self) -> ResolverHealth:
        """Lightweight probe to verify whether the underlying CLI/service is functional."""
        ...

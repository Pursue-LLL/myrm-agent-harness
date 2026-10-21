"""External secret reference resolution domain.

[INPUT]
- .protocols::ExternalSecretResolver, ResolverHealth
- .manager::ExternalSecretsManager, ExternalSecretResolutionError,
  is_external_secret_reference, get_external_secrets_manager

[OUTPUT]
- ExternalSecretResolver
- ResolverHealth
- ExternalSecretsManager
- ExternalSecretResolutionError
- is_external_secret_reference
- get_external_secrets_manager
- resolve_external_secret
- invalidate_external_secret

[POS]
Harness core security domain public facade for external vault credential resolution (1Password/Bitwarden).
"""

from __future__ import annotations

from myrm_agent_harness.core.security.external_secrets.manager import (
    ExternalSecretResolutionError,
    ExternalSecretsManager,
    get_external_secrets_manager,
    is_external_secret_reference,
)
from myrm_agent_harness.core.security.external_secrets.protocols import (
    ExternalSecretResolver,
    ResolverHealth,
)


def resolve_external_secret(reference: str, force_refresh: bool = False) -> str:
    """Resolve an external secret reference (op://, bw://, bws://) to plaintext in memory."""
    return get_external_secrets_manager().resolve(reference, force_refresh=force_refresh)


def invalidate_external_secret(reference: str) -> None:
    """Invalidate cached value for reference (called on HTTP 401/403 to trigger auto-rotation)."""
    get_external_secrets_manager().invalidate(reference)


__all__ = [
    "ExternalSecretResolutionError",
    "ExternalSecretResolver",
    "ExternalSecretsManager",
    "ResolverHealth",
    "get_external_secrets_manager",
    "invalidate_external_secret",
    "is_external_secret_reference",
    "resolve_external_secret",
]

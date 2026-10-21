"""Agent Secrets Backend Module.

[INPUT]
- .protocols::AgentSecretBackend (POS: Protocol for Agent Secret Storage Backend.)
- core.security.external_secrets::resolve_external_secret and helpers (POS: external secret reference resolution)

[OUTPUT]
- AgentSecretBackend: Protocol for Agent Secret Storage Backend
- ExternalSecretResolutionError, is_external_secret_reference, resolve_external_secret, invalidate_external_secret: external secret reference helpers

[POS]
Agent secrets backend package entry point. Re-exports the storage protocol and external secret reference helpers;
storage implementations are provided by the host.
"""

from myrm_agent_harness.core.security.external_secrets import (
    ExternalSecretResolutionError,
    invalidate_external_secret,
    is_external_secret_reference,
    resolve_external_secret,
)

from .protocols import AgentSecretBackend

__all__ = [
    "AgentSecretBackend",
    "ExternalSecretResolutionError",
    "invalidate_external_secret",
    "is_external_secret_reference",
    "resolve_external_secret",
]

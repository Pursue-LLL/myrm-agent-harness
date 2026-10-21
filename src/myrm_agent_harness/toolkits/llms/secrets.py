"""External secret reference resolver for 1Password and Bitwarden (Compatibility Facade).

[INPUT]
- core.security.external_secrets::resolve_external_secret, invalidate_external_secret,
  is_external_secret_reference, ExternalSecretResolutionError (POS: Foundation security primitive)

[OUTPUT]
- is_external_secret_reference: Helper to test whether a value is an op:// or bw:// URI
- resolve_external_secret: Resolves op:// or bw:// reference dynamically via local CLI with LRU caching
- invalidate_external_secret: Evicts cached secret for reference (auto-rotation on 401)
- ExternalSecretResolutionError: Raised on resolution failure or timeout

[POS]
toolkits/llms/ facade re-exporting from core.security.external_secrets.
Maintains backwards compatibility for callers while delegating to the unified
memory-cached manager in core.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.external_secrets import (
    ExternalSecretResolutionError,
    invalidate_external_secret,
    is_external_secret_reference,
    resolve_external_secret,
)

__all__ = [
    "ExternalSecretResolutionError",
    "invalidate_external_secret",
    "is_external_secret_reference",
    "resolve_external_secret",
]

"""Optional server-injected workspace trust lookup registry.

[INPUT]
- protocol::WorkspaceTrustLookup (POS: Resolve trust level for canonical workspace paths)

[OUTPUT]
- set_workspace_trust_lookup / get_workspace_trust_lookup: register server store
- resolve_workspace_trust_level: fail-closed when lookup missing or path undecided

[POS]
Harness-side indirection so agent runs resolve trust without importing server code.
"""

from __future__ import annotations

from .protocol import WorkspaceTrustLookup
from .types import WorkspaceTrustLevel

_lookup: WorkspaceTrustLookup | None = None


def set_workspace_trust_lookup(lookup: WorkspaceTrustLookup | None) -> None:
    """Register or clear the active workspace trust lookup (server sets at startup)."""
    global _lookup
    _lookup = lookup


def get_workspace_trust_lookup() -> WorkspaceTrustLookup | None:
    """Return the registered lookup, if any."""
    return _lookup


def resolve_workspace_trust_level(workspace_root: str) -> WorkspaceTrustLevel:
    """Resolve effective trust for *workspace_root* (unknown → RESTRICTED)."""
    lookup = _lookup
    if lookup is None:
        return WorkspaceTrustLevel.RESTRICTED
    canonical = lookup.normalize_path(workspace_root)
    if not canonical:
        return WorkspaceTrustLevel.RESTRICTED
    stored = lookup.get_level(canonical)
    if stored is None:
        return WorkspaceTrustLevel.RESTRICTED
    return stored

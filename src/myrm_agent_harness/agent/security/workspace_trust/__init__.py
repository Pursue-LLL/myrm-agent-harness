"""Unified workspace trust gate — folder bind + side-channel execution control.

[INPUT]
- None at import time; re-exports the gate, manifest, policy and runtime helpers

[OUTPUT]
- Gate API: blocks_workspace_side_channels, assert_mcp_spawn_allowed,
  is_path_within_workspace, matches_repo_command_prefix
- Lifecycle API: apply_workspace_trust_for_root, clear_workspace_trust_runtime
- Lookup seam: WorkspaceTrustLookup, set/get_workspace_trust_lookup,
  resolve_workspace_trust_level
- Types: WorkspaceTrustLevel, WorkspaceTrustManifest, WorkspaceTrustEntry

[POS]
Public surface of the workspace_trust subpackage. Import from here rather than from the
individual modules so the internal layout stays free to change. Located under
`agent/security/`, deliberately not in `toolkits/`; the server owns persistence and REST,
the control plane is untouched.
"""

from __future__ import annotations

from .context import (
    clear_workspace_trust_context,
    get_repo_command_prefixes,
    get_workspace_trust_level,
    set_repo_command_prefixes,
    set_workspace_trust_level,
)
from .errors import WorkspaceTrustBlockedError
from .gate import (
    assert_mcp_spawn_allowed,
    blocks_workspace_side_channels,
    is_path_within_workspace,
    matches_repo_command_prefix,
)
from .manifest import build_workspace_trust_manifest, canonicalize_workspace_path, manifest_hash
from .protocol import WorkspaceTrustLookup
from .provider import (
    get_workspace_trust_lookup,
    resolve_workspace_trust_level,
    set_workspace_trust_lookup,
)
from .repo_policy import load_repo_command_prefixes
from .runtime import apply_workspace_trust_for_root, clear_workspace_trust_runtime
from .types import WorkspaceTrustEntry, WorkspaceTrustLevel, WorkspaceTrustManifest

__all__ = [
    "WorkspaceTrustBlockedError",
    "WorkspaceTrustEntry",
    "WorkspaceTrustLevel",
    "WorkspaceTrustLookup",
    "WorkspaceTrustManifest",
    "apply_workspace_trust_for_root",
    "assert_mcp_spawn_allowed",
    "blocks_workspace_side_channels",
    "build_workspace_trust_manifest",
    "canonicalize_workspace_path",
    "clear_workspace_trust_context",
    "clear_workspace_trust_runtime",
    "get_repo_command_prefixes",
    "get_workspace_trust_level",
    "get_workspace_trust_lookup",
    "is_path_within_workspace",
    "load_repo_command_prefixes",
    "manifest_hash",
    "matches_repo_command_prefix",
    "resolve_workspace_trust_level",
    "set_repo_command_prefixes",
    "set_workspace_trust_level",
    "set_workspace_trust_lookup",
]

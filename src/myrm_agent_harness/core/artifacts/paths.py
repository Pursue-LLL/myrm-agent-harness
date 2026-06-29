"""Workspace artifact vault path resolution — framework-agnostic.

[INPUT]
- pathlib::Path (POS: Python path library)
- os.getenv (POS: optional deployment override)

[OUTPUT]
- WORKSPACE_AGENT_DIR_NAME, ARTIFACT_VAULT_DIR_NAME: default path segment constants
- workspace_vault_relative_parts(): validated relative segments under workspace root
- resolve_workspace_artifact_vault_dir(): absolute vault directory under a task workspace

[POS]
Single source of truth for on-disk artifact vault layout under a task workspace root.
Usable by toolkits/, agent/, and server without brand-specific path literals.
"""

from __future__ import annotations

import os
from pathlib import Path

# Hidden directory under task workspace for agent runtime artifacts (vault, etc.)
WORKSPACE_AGENT_DIR_NAME = ".agent"
ARTIFACT_VAULT_DIR_NAME = "vault"

_ENV_WORKSPACE_VAULT_RELATIVE = "AGENT_WORKSPACE_VAULT_RELATIVE"


def _parse_vault_relative_override(raw: str) -> tuple[str, ...]:
    """Parse and validate AGENT_WORKSPACE_VAULT_RELATIVE segments."""
    stripped = raw.strip()
    if stripped.startswith(("/", "\\")) or (len(stripped) > 1 and stripped[1] == ":"):
        msg = f"{_ENV_WORKSPACE_VAULT_RELATIVE} must be a relative path under the workspace root"
        raise ValueError(msg)
    cleaned = stripped.strip("/")
    if not cleaned:
        msg = f"{_ENV_WORKSPACE_VAULT_RELATIVE} must not be empty when set"
        raise ValueError(msg)
    parts = tuple(part for part in cleaned.split("/") if part)
    if not parts:
        msg = f"{_ENV_WORKSPACE_VAULT_RELATIVE} must contain at least one path segment"
        raise ValueError(msg)
    if any(part in (".", "..") for part in parts):
        msg = f"{_ENV_WORKSPACE_VAULT_RELATIVE} must not contain '.' or '..' segments"
        raise ValueError(msg)
    return parts


def workspace_vault_relative_parts() -> tuple[str, ...]:
    """Return path segments from workspace root to artifact vault directory."""
    override = os.getenv(_ENV_WORKSPACE_VAULT_RELATIVE, "").strip()
    if override:
        return _parse_vault_relative_override(override)
    return (WORKSPACE_AGENT_DIR_NAME, ARTIFACT_VAULT_DIR_NAME)


def resolve_workspace_artifact_vault_dir(workspace_root: str | Path) -> Path:
    """Resolve artifact vault directory for a task workspace root."""
    base = Path(workspace_root).expanduser().resolve()
    return base.joinpath(*workspace_vault_relative_parts())

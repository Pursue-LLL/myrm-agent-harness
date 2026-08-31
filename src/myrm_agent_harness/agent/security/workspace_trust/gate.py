"""Pure gate helpers for workspace trust side-channel enforcement."""

from __future__ import annotations

import os
from pathlib import Path

from .types import WorkspaceTrustLevel


def blocks_workspace_side_channels(level: WorkspaceTrustLevel | None) -> bool:
    """Return True when repo-local side channels must stay disabled."""
    if level is None or level in {WorkspaceTrustLevel.RESTRICTED, WorkspaceTrustLevel.REVOKED}:
        return True
    return False


def is_path_within_workspace(candidate: str | None, workspace_root: str | None) -> bool:
    """Return True when *candidate* resolves under *workspace_root*."""
    if not candidate or not workspace_root:
        return False
    try:
        child = Path(os.path.realpath(os.path.expanduser(candidate)))
        root = Path(os.path.realpath(os.path.expanduser(workspace_root)))
        child.relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def assert_mcp_spawn_allowed(
    *,
    workspace_root: str | None,
    cwd: str | None,
    plugin_root: str | None,
    trust_level: WorkspaceTrustLevel | None,
) -> None:
    """Block MCP subprocess spawn from an untrusted workspace scope."""
    if blocks_workspace_side_channels(trust_level):
        scoped = any(
            is_path_within_workspace(path, workspace_root)
            for path in (cwd, plugin_root)
        )
        if scoped:
            from .errors import WorkspaceTrustBlockedError

            raise WorkspaceTrustBlockedError(
                "Workspace trust gate blocked MCP spawn: this folder is not trusted. "
                "Trust the folder when binding the project workspace to enable local MCP servers.",
                reason="mcp_spawn_blocked",
            )


def matches_repo_command_prefix(command: str, prefixes: tuple[str, ...]) -> bool:
    """Return True when *command* starts with a trusted repo-declared prefix."""
    from myrm_agent_harness.agent.security.command_allowlist_pattern import (
        is_compound_shell_command,
    )

    normalized = command.strip()
    if not normalized or not prefixes or is_compound_shell_command(normalized):
        return False
    return any(normalized.startswith(prefix) for prefix in prefixes)

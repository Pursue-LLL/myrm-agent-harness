"""Runtime ContextVars for workspace trust during agent execution."""

from __future__ import annotations

from contextvars import ContextVar

from .types import WorkspaceTrustLevel

_workspace_trust_level_var: ContextVar[WorkspaceTrustLevel | None] = ContextVar(
    "workspace_trust_level",
    default=None,
)
_repo_command_prefixes_var: ContextVar[tuple[str, ...]] = ContextVar(
    "repo_command_prefixes",
    default=(),
)


def set_workspace_trust_level(level: WorkspaceTrustLevel | None) -> None:
    """Bind the active workspace trust level for the current async context."""
    _workspace_trust_level_var.set(level)


def get_workspace_trust_level() -> WorkspaceTrustLevel | None:
    """Return the active workspace trust level, if any."""
    return _workspace_trust_level_var.get()


def set_repo_command_prefixes(prefixes: tuple[str, ...]) -> None:
    """Bind repo-declared command prefixes effective only for trusted workspaces."""
    _repo_command_prefixes_var.set(prefixes)


def get_repo_command_prefixes() -> tuple[str, ...]:
    """Return repo command prefixes bound for the current async context."""
    return _repo_command_prefixes_var.get()


def clear_workspace_trust_context() -> None:
    """Reset trust-related ContextVars at run end."""
    _workspace_trust_level_var.set(None)
    _repo_command_prefixes_var.set(())

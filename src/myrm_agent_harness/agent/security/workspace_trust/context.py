"""Runtime ContextVars for workspace trust during agent execution.

[INPUT]
- contextvars::ContextVar (POS: Python 异步上下文变量标准库)
- agent.security.workspace_trust.types::WorkspaceTrustLevel
  (POS: 工作区信任级别类型)

[OUTPUT]
- set/get_workspace_trust_level and set/get_repo_command_prefixes accessors
- clear_workspace_trust_context: resets both vars at run end

[POS]
Run-scoped state holder of the workspace_trust gate. ContextVars keep the decision
isolated per async task, so concurrent runs on different workspaces never observe each
other's trust level. Values are populated by runtime.py from a server-injected lookup.
"""

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

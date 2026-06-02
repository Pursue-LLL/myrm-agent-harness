"""ContextVar binding for WorkspaceService filesystem root within an agent Task.

[INPUT]
(none — framework-local utility)

[OUTPUT]
- bind_workspace_storage_root / release_workspace_storage_bind_token / workspace_storage_fs_root_strict

[POS]
Binds aggregate workspace storage root inside an asyncio Task so lazy helpers align with `setup_workspace`.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from pathlib import Path

_workspace_storage_fs_root: ContextVar[Path | None] = ContextVar("_workspace_storage_fs_root", default=None)


def bind_workspace_storage_root(root: Path) -> Token:
    """Bind aggregate workspace storage root for the current asyncio Task."""
    return _workspace_storage_fs_root.set(Path(root).expanduser().resolve())


def release_workspace_storage_bind_token(token: object | None) -> None:
    """Reset ContextVar layer created by :func:`bind_workspace_storage_root`."""
    if token is None:
        return
    if isinstance(token, Token):
        _workspace_storage_fs_root.reset(token)


def workspace_storage_fs_root_strict() -> Path:
    """Return bound root or raise — used when constructing WorkspaceService lazily."""
    root = _workspace_storage_fs_root.get()
    if root is None:
        raise RuntimeError(
            "workspace storage root not bound: expected merged_context['workspaces_storage_root'] "
            "and bind_workspace_storage_root() from setup_workspace"
        )
    return root

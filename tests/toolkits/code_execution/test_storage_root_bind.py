"""Unit tests for workspace aggregate-root ContextVar binding."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
    bind_workspace_storage_root,
    release_workspace_storage_bind_token,
    workspace_storage_fs_root_strict,
)


def test_bind_then_release_restores_state(tmp_path: Path) -> None:
    root = tmp_path / "agg"
    root.mkdir()
    token = bind_workspace_storage_root(root)
    assert workspace_storage_fs_root_strict() == root.resolve()
    release_workspace_storage_bind_token(token)
    with pytest.raises(RuntimeError, match="workspace storage root not bound"):
        workspace_storage_fs_root_strict()


def test_release_without_bind_is_safe() -> None:
    release_workspace_storage_bind_token(None)

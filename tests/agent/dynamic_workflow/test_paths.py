"""Unit tests for workflow events DB path resolution."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.agent.dynamic_workflow.paths import resolve_workflow_events_db_path
from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
    bind_workspace_storage_root,
    release_workspace_storage_bind_token,
)


def test_resolve_workflow_events_db_path_explicit_harness_root(tmp_path: Path) -> None:
    harness_root = tmp_path / "harness-data"
    harness_root.mkdir()
    resolved = resolve_workflow_events_db_path(harness_root=harness_root)
    assert resolved == harness_root / ".myrm" / "workflow_events.db"


def test_resolve_workflow_events_db_path_bound_storage_root(tmp_path: Path) -> None:
    token = bind_workspace_storage_root(tmp_path)
    try:
        resolved = resolve_workflow_events_db_path()
        assert resolved == tmp_path / ".myrm" / "workflow_events.db"
    finally:
        release_workspace_storage_bind_token(token)


def test_resolve_workflow_events_db_path_prefers_explicit_over_bound(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    token = bind_workspace_storage_root(tmp_path / "bound")
    try:
        resolved = resolve_workflow_events_db_path(harness_root=explicit)
        assert resolved == explicit / ".myrm" / "workflow_events.db"
    finally:
        release_workspace_storage_bind_token(token)


def test_reset_cache_picks_up_a_new_workspace(monkeypatch, tmp_path) -> None:
    """The resolver memoizes across the process; stale roots must be clearable.

    Without a reset, whatever first called resolve_workspace_root (e.g. a test
    harness repo) pinned the value for every later session.
    """
    from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import (
        WorkspacePathResolver,
    )

    first = tmp_path / "ws_a"
    second = tmp_path / "ws_b"
    first.mkdir()
    second.mkdir()

    WorkspacePathResolver.reset_cache()
    monkeypatch.setenv("WORKSPACE_ROOT", str(first))
    assert WorkspacePathResolver.resolve_workspace_root() == first.resolve()

    WorkspacePathResolver.reset_cache()
    monkeypatch.setenv("WORKSPACE_ROOT", str(second))
    assert WorkspacePathResolver.resolve_workspace_root() == second.resolve()

    WorkspacePathResolver.reset_cache()


def test_workspace_switch_re_resolves_without_explicit_reset(monkeypatch, tmp_path) -> None:
    """A new session root must invalidate the memo automatically.

    Relying on every caller to remember reset_cache means one forgotten call pins
    the previous tenant's workspace root for the whole process.
    """
    from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import (
        WorkspacePathResolver,
    )

    first = tmp_path / "tenant_a"
    second = tmp_path / "tenant_b"
    first.mkdir()
    second.mkdir()

    WorkspacePathResolver.reset_cache()
    monkeypatch.setenv("WORKSPACE_ROOT", str(first))
    assert WorkspacePathResolver.resolve_workspace_root() == first.resolve()

    # No reset_cache(): changing the input alone must be enough.
    monkeypatch.setenv("WORKSPACE_ROOT", str(second))
    assert WorkspacePathResolver.resolve_workspace_root() == second.resolve()

    WorkspacePathResolver.reset_cache()

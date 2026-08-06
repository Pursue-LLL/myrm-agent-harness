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

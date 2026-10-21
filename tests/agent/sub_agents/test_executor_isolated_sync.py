"""Ensure ISOLATED_COPY sync_back runs before temp workspace teardown."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.sub_agents.workspace_isolation import (
    _clone_workspace,
    isolated_workspace,
)


@pytest.mark.asyncio
async def test_isolated_workspace_sync_before_cleanup(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "seed.txt").write_text("before", encoding="utf-8")

    async with isolated_workspace(parent) as (child_ws, sync_back):
        (child_ws / "seed.txt").write_text("after", encoding="utf-8")
        await sync_back()

    assert (parent / "seed.txt").read_text(encoding="utf-8") == "after"


@pytest.mark.asyncio
async def test_deferred_sync_via_batch_merge_pattern(tmp_path: Path) -> None:
    """Simulate defer: child edits, merge after context exits would fail without batch merge."""
    parent = tmp_path / "parent"
    parent.mkdir()
    child = tmp_path / "child"
    child.mkdir()
    _clone_workspace(parent, child)
    (child / "new.txt").write_text("ok", encoding="utf-8")

    from myrm_agent_harness.agent.sub_agents.workspace_isolation import _sync_tree

    _sync_tree(child, parent)
    assert (parent / "new.txt").read_text(encoding="utf-8") == "ok"

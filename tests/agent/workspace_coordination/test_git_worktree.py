"""Unit tests for Git Worktree isolation and policy enforcement."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, WorkspacePolicy
from myrm_agent_harness.agent.workspace_coordination.git_worktree import (
    build_worktree_context_note,
    create_subagent_worktree,
    finalize_subagent_worktree,
    resolve_repo_root,
)
from myrm_agent_harness.agent.workspace_coordination.policy import (
    apply_parallel_write_isolation,
)


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary initialized git repository with one commit."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    
    readme = repo / "README.md"
    readme.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, check=True, capture_output=True)
    return repo


def test_resolve_repo_root_non_git(tmp_path: Path) -> None:
    non_git = tmp_path / "not_git"
    non_git.mkdir()
    assert resolve_repo_root(non_git) is None
    assert resolve_repo_root(None) is None


def test_resolve_repo_root_valid(temp_git_repo: Path) -> None:
    sub_dir = temp_git_repo / "src"
    sub_dir.mkdir()
    resolved = resolve_repo_root(sub_dir)
    assert resolved is not None
    assert Path(resolved).resolve() == temp_git_repo.resolve()


def test_worktree_lifecycle_clean_prune(temp_git_repo: Path) -> None:
    info = create_subagent_worktree(temp_git_repo, subagent_id="child-1")
    assert info is not None
    assert "path" in info
    assert "branch" in info
    wt_path = Path(info["path"])
    assert wt_path.exists()
    assert (wt_path / "README.md").exists()

    note = build_worktree_context_note(info)
    assert "[WORKTREE ISOLATION]" in note
    assert info["branch"] in note

    # Finalize without any changes -> clean prune
    finalized = finalize_subagent_worktree(info, prune=True)
    assert finalized["commits"] == 0
    assert finalized["dirty"] is False
    assert finalized["pruned"] is True
    assert not wt_path.exists()


def test_worktree_lifecycle_dirty_preserved(temp_git_repo: Path) -> None:
    info = create_subagent_worktree(temp_git_repo, subagent_id="child-dirty")
    assert info is not None
    wt_path = Path(info["path"])

    # Make uncommitted change in worktree
    (wt_path / "new_file.txt").write_text("uncommitted work", encoding="utf-8")

    finalized = finalize_subagent_worktree(info, prune=True)
    assert finalized["dirty"] is True
    assert finalized["pruned"] is False
    assert wt_path.exists()


def test_apply_parallel_write_isolation_git(temp_git_repo: Path) -> None:
    config = SubagentConfig(system_prompt="You are a helpful worker.")
    child_context: dict[str, object] = {"workspace_path": str(temp_git_repo)}

    updated_config, updated_ctx = apply_parallel_write_isolation(
        config=config,
        child_context=child_context,
        readonly=False,
        parallel_write_batch=True,
    )

    assert updated_config.workspace_policy == WorkspacePolicy.GIT_WORKTREE
    assert "[WORKTREE ISOLATION]" in updated_config.system_prompt
    assert "_git_worktree_info" in updated_ctx
    assert updated_ctx["_parallel_write_batch"] is True


def test_apply_parallel_write_isolation_fallback_non_git(tmp_path: Path) -> None:
    non_git = tmp_path / "plain_dir"
    non_git.mkdir()
    config = SubagentConfig(system_prompt="You are a helpful worker.")
    child_context: dict[str, object] = {"workspace_path": str(non_git)}

    updated_config, updated_ctx = apply_parallel_write_isolation(
        config=config,
        child_context=child_context,
        readonly=False,
        parallel_write_batch=True,
    )

    assert updated_config.workspace_policy == WorkspacePolicy.ISOLATED_COPY
    assert updated_ctx["_defer_workspace_merge"] is True

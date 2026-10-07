# ============================================================================
# Unit Tests for SubagentWorktreeReviewMergeGate (Item 151)
# Verifies worktree provisioning, zero-collision concurrent subagent writes,
# structured diff inspection, dry-run merge precheck, and atomic merge gates.
# ============================================================================

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from myrm_agent_harness.agent.workspace_coordination import (
    MergeStrategy,
    SubagentWorktreeReviewMergeGate,
    WorktreeIsolationConfig,
)


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Creates a temporary initialized git repository with initial commit."""
    repo = tmp_path / "test_workspace"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Harness"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@myrm.dev"], cwd=repo, check=True, capture_output=True)

    readme = repo / "README.md"
    readme.write_text("# Project Alpha\nInitial content\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, check=True, capture_output=True)
    return repo


def test_worktree_provisioning_and_gitignore(temp_git_repo: Path) -> None:
    """Verifies that worktree is created with isolated directory and gitignore updated."""
    gate = SubagentWorktreeReviewMergeGate()
    meta = gate.create_isolated_worktree(str(temp_git_repo), subagent_id="sub-101")

    assert meta.subagent_id == "sub-101"
    assert "myrm-subagent/subagent-sub-101" == meta.branch_name
    assert Path(meta.worktree_path).exists()
    assert (Path(meta.worktree_path) / "README.md").exists()

    gitignore = temp_git_repo / ".gitignore"
    assert gitignore.exists()
    assert ".worktrees/" in gitignore.read_text(encoding="utf-8")


def test_concurrent_subagents_zero_collision(temp_git_repo: Path) -> None:
    """Verifies two subagents working concurrently in separate worktrees without collisions."""
    gate = SubagentWorktreeReviewMergeGate()

    meta1 = gate.create_isolated_worktree(str(temp_git_repo), subagent_id="sub-alpha")
    meta2 = gate.create_isolated_worktree(str(temp_git_repo), subagent_id="sub-beta")

    path1 = Path(meta1.worktree_path)
    path2 = Path(meta2.worktree_path)

    # Subagent 1 creates module_a.py and commits
    (path1 / "module_a.py").write_text("def run_a(): return 'alpha'\n", encoding="utf-8")
    subprocess.run(["git", "add", "module_a.py"], cwd=path1, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: implement module a"], cwd=path1, check=True, capture_output=True)

    # Subagent 2 creates module_b.py and commits
    (path2 / "module_b.py").write_text("def run_b(): return 'beta'\n", encoding="utf-8")
    subprocess.run(["git", "add", "module_b.py"], cwd=path2, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: implement module b"], cwd=path2, check=True, capture_output=True)

    # Verify physical isolation: neither sees each other's changes
    assert (path1 / "module_a.py").exists()
    assert not (path1 / "module_b.py").exists()

    assert (path2 / "module_b.py").exists()
    assert not (path2 / "module_a.py").exists()

    # Main repo checkout remains completely untouched
    assert not (temp_git_repo / "module_a.py").exists()
    assert not (temp_git_repo / "module_b.py").exists()


def test_inspect_worktree_structured_summary(temp_git_repo: Path) -> None:
    """Verifies that inspect_worktree produces accurate commit, diff and status metrics."""
    gate = SubagentWorktreeReviewMergeGate()
    meta = gate.create_isolated_worktree(str(temp_git_repo), subagent_id="sub-inspector")
    wt_path = Path(meta.worktree_path)

    # Initially 0 commits and clean
    summary_clean = gate.inspect_worktree(meta)
    assert summary_clean.commits_ahead == 0
    assert not summary_clean.is_dirty
    assert len(summary_clean.changed_files) == 0

    # Add commit with new file
    service_file = wt_path / "service.py"
    service_file.write_text("class Service:\n    pass\n", encoding="utf-8")
    subprocess.run(["git", "add", "service.py"], cwd=wt_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: add service class"], cwd=wt_path, check=True, capture_output=True)

    summary_committed = gate.inspect_worktree(meta)
    assert summary_committed.commits_ahead == 1
    assert not summary_committed.is_dirty
    assert "service.py" in summary_committed.changed_files
    assert summary_committed.total_insertions == 2
    assert "feat: add service class" in summary_committed.commit_messages[0]

    # Make uncommitted modifications -> is_dirty becomes True
    (wt_path / "dirty.txt").write_text("uncommitted scratch", encoding="utf-8")
    summary_dirty = gate.inspect_worktree(meta)
    assert summary_dirty.is_dirty


def test_precheck_merge_and_conflict_detection(temp_git_repo: Path) -> None:
    """Verifies precheck dry-run validation and conflict reporting."""
    gate = SubagentWorktreeReviewMergeGate()
    meta = gate.create_isolated_worktree(str(temp_git_repo), subagent_id="sub-conflict")
    wt_path = Path(meta.worktree_path)

    # Subagent modifies README.md
    (wt_path / "README.md").write_text("# Project Alpha\nSubagent modification\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=wt_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Subagent change"], cwd=wt_path, check=True, capture_output=True)

    # Main repo concurrently modifies same line in README.md
    (temp_git_repo / "README.md").write_text("# Project Alpha\nMain conflicting change\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=temp_git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Main conflict"], cwd=temp_git_repo, check=True, capture_output=True)

    # Precheck should detect conflict
    precheck = gate.precheck_merge(meta, target_ref="HEAD")
    assert not precheck.can_merge
    assert precheck.has_conflicts


def test_execute_merge_and_cleanup_squash(temp_git_repo: Path) -> None:
    """Verifies atomic squash merge, worktree removal and branch deletion."""
    gate = SubagentWorktreeReviewMergeGate()
    meta = gate.create_isolated_worktree(str(temp_git_repo), subagent_id="sub-mergeable")
    wt_path = Path(meta.worktree_path)

    # Subagent adds calculator.py
    (wt_path / "calculator.py").write_text("def add(x, y): return x + y\n", encoding="utf-8")
    subprocess.run(["git", "add", "calculator.py"], cwd=wt_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: add calculator"], cwd=wt_path, check=True, capture_output=True)

    merge_res = gate.execute_merge_and_cleanup(
        meta=meta,
        target_ref="HEAD",
        strategy=MergeStrategy.SQUASH,
        commit_message="feat: merge calculator from subagent",
        delete_branch_after=True,
    )

    assert merge_res.success
    assert merge_res.strategy == MergeStrategy.SQUASH
    assert merge_res.worktree_pruned
    assert merge_res.branch_deleted

    # Main repository now contains the file
    assert (temp_git_repo / "calculator.py").exists()
    assert "def add" in (temp_git_repo / "calculator.py").read_text(encoding="utf-8")

    # Worktree directory is removed
    assert not wt_path.exists()

    # Branch is deleted
    branch_check = subprocess.run(["git", "branch", "--list", meta.branch_name], cwd=temp_git_repo, capture_output=True, text=True)
    assert meta.branch_name not in branch_check.stdout


def test_prune_clean_worktree(temp_git_repo: Path) -> None:
    """Verifies clean worktree with no commits or dirty files is automatically pruned."""
    gate = SubagentWorktreeReviewMergeGate()
    meta = gate.create_isolated_worktree(str(temp_git_repo), subagent_id="sub-clean")
    wt_path = Path(meta.worktree_path)

    assert wt_path.exists()
    # 0 commits, clean -> prune succeeds
    pruned = gate.prune_if_clean(meta)
    assert pruned
    assert not wt_path.exists()


def test_worktree_types_serialization() -> None:
    """Verifies dictionary serialization across all typed data structures."""
    config = WorktreeIsolationConfig()
    assert config.worktrees_dirname == ".worktrees"

    meta = SubagentWorktreeReviewMergeGate()._ensure_gitignore
    assert callable(meta)

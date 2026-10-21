"""Unit tests for IsolatedCommitGuard.

Verifies:
1. build_commit_args accurately appends --no-verify and handles path specifications.
2. build_isolated_commit_env properly sets HUSKY=0 and PRE_COMMIT_ALLOW_NO_CONFIG=1.
3. ISOLATED_CHECKPOINT commits bypass failing git pre-commit hooks (Husky / pre-commit).
4. USER_EXPLICIT_COMMIT still triggers git hooks, upholding user-level code validation.
5. Path-restricted commits commit only targeted files, keeping remaining staged files staged.
6. commit_worktree_isolated integrates cleanly with git_worktree.py.
7. Subprocess timeout expiration is caught cleanly to prevent infinite deadlock.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from unittest.mock import patch
import pytest

from myrm_agent_harness.agent.workspace_coordination.git_worktree import (
    commit_worktree_isolated,
    create_subagent_worktree,
)
from myrm_agent_harness.agent.workspace_coordination.isolated_commit_guard import (
    CommitIntent,
    build_commit_args,
    build_isolated_commit_env,
    run_isolated_commit,
    should_skip_hooks,
)


def _init_git_repo(repo_dir: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)


def _install_failing_pre_commit_hook(repo_dir: Path) -> Path:
    hook_dir = repo_dir / ".git" / "hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook_file = hook_dir / "pre-commit"
    hook_file.write_text("#!/bin/sh\necho 'pre-commit hook failed' >&2\nexit 1\n", encoding="utf-8")
    hook_file.chmod(0o755)
    return hook_file


def test_build_commit_args_with_and_without_paths() -> None:
    # 1. No paths, skip_hooks=True
    args1 = build_commit_args("snapshot commit", skip_hooks=True)
    assert args1 == ["commit", "--no-verify", "-m", "snapshot commit"]

    # 2. No paths, skip_hooks=False
    args2 = build_commit_args("user commit", skip_hooks=False)
    assert args2 == ["commit", "-m", "user commit"]

    # 3. Specific paths, skip_hooks=True
    args3 = build_commit_args("partial commit", ["src/a.py", "docs/b.md"], skip_hooks=True)
    assert args3 == ["--literal-pathspecs", "commit", "--no-verify", "-m", "partial commit", "--", "src/a.py", "docs/b.md"]

    # 4. Specific paths, skip_hooks=False
    args4 = build_commit_args("partial user commit", ["src/a.py"], skip_hooks=False)
    assert args4 == ["--literal-pathspecs", "commit", "-m", "partial user commit", "--", "src/a.py"]


def test_should_skip_hooks() -> None:
    assert should_skip_hooks(CommitIntent.ISOLATED_CHECKPOINT) is True
    assert should_skip_hooks(CommitIntent.INTERNAL_SYNC) is True
    assert should_skip_hooks(CommitIntent.USER_EXPLICIT_COMMIT) is False


def test_build_isolated_commit_env_sets_husky_0() -> None:
    env_skip = build_isolated_commit_env({"CUSTOM_VAR": "1"}, skip_hooks=True)
    assert env_skip["CUSTOM_VAR"] == "1"
    assert env_skip["HUSKY"] == "0"
    assert env_skip["PRE_COMMIT_ALLOW_NO_CONFIG"] == "1"

    env_noskip = build_isolated_commit_env({"CUSTOM_VAR": "1"}, skip_hooks=False)
    assert env_noskip["CUSTOM_VAR"] == "1"
    assert "HUSKY" not in env_noskip


def test_isolated_checkpoint_skips_failing_pre_commit_hook(tmp_path: Path) -> None:
    repo = tmp_path / "repo_skip"
    repo.mkdir()
    _init_git_repo(repo)
    _install_failing_pre_commit_hook(repo)

    file_a = repo / "note.txt"
    file_a.write_text("automated checkpoint content\n", encoding="utf-8")
    subprocess.run(["git", "add", "note.txt"], cwd=repo, check=True)

    # Isolated commit should skip the failing hook via --no-verify and succeed
    result = run_isolated_commit(
        cwd=repo,
        message="[auto] checkpoint",
        intent=CommitIntent.ISOLATED_CHECKPOINT,
    )
    assert result.success is True
    assert result.skipped_hooks is True
    assert result.commit_hash is not None
    assert result.error is None

    # Verify commit in git log
    log_proc = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert log_proc.stdout.strip() == "[auto] checkpoint"


def test_user_explicit_commit_still_runs_hooks_and_fails_if_hook_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo_user"
    repo.mkdir()
    _init_git_repo(repo)
    _install_failing_pre_commit_hook(repo)

    file_b = repo / "user_code.py"
    file_b.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "user_code.py"], cwd=repo, check=True)

    # User explicit commit preserves hook execution and should fail
    result = run_isolated_commit(
        cwd=repo,
        message="feat: user update",
        intent=CommitIntent.USER_EXPLICIT_COMMIT,
    )
    assert result.success is False
    assert result.skipped_hooks is False
    assert result.commit_hash is None
    assert result.error is not None
    assert "pre-commit hook failed" in result.error


def test_path_restricted_commit_only_commits_specified_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo_paths"
    repo.mkdir()
    _init_git_repo(repo)

    f1 = repo / "file1.txt"
    f2 = repo / "file2.txt"
    f1.write_text("f1\n", encoding="utf-8")
    f2.write_text("f2\n", encoding="utf-8")
    subprocess.run(["git", "add", "file1.txt", "file2.txt"], cwd=repo, check=True)

    # Commit only file1.txt
    res = run_isolated_commit(
        cwd=repo,
        message="commit file1 only",
        paths=["file1.txt"],
        intent=CommitIntent.ISOLATED_CHECKPOINT,
    )
    assert res.success is True

    # Check status: file2.txt must remain staged in the index
    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [ln.strip() for ln in status_proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert "A  file2.txt" in lines[0]


def test_commit_worktree_isolated_integration(tmp_path: Path) -> None:
    repo = tmp_path / "repo_wt"
    repo.mkdir()
    _init_git_repo(repo)

    init_file = repo / "README.md"
    init_file.write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)

    _install_failing_pre_commit_hook(repo)

    wt_info = create_subagent_worktree(repo, subagent_id="test-sub-1")
    assert wt_info is not None
    wt_path = Path(wt_info["path"])

    wt_file = wt_path / "worktree_task.txt"
    wt_file.write_text("isolated task content\n", encoding="utf-8")
    subprocess.run(["git", "add", "worktree_task.txt"], cwd=wt_path, check=True)

    # Execute isolated commit inside worktree
    res = commit_worktree_isolated(wt_info, "[worktree] internal snapshot")
    assert res.success is True
    assert res.skipped_hooks is True
    assert res.commit_hash is not None

    # Non-existent path returns graceful error
    res_err = commit_worktree_isolated({"path": "/non/existent/path"}, "fail")
    assert res_err.success is False
    assert "Invalid worktree path" in str(res_err.error)


def test_isolated_commit_timeout_protection(tmp_path: Path) -> None:
    repo = tmp_path / "repo_timeout"
    repo.mkdir()

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=5)):
        res = run_isolated_commit(
            cwd=repo,
            message="timeout commit",
            timeout_seconds=5,
        )
        assert res.success is False
        assert res.error is not None
        assert "timed out after 5s" in res.error
        assert "un-isolated git hook deadlock" in res.error

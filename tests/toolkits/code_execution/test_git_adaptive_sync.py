"""Unit tests for Git adaptive repository sync policy and pitfall memory creation."""

from __future__ import annotations

from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.code_execution.git_digest import (
    RepoSyncDecision,
    evaluate_repo_sync_policy,
)
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    create_pitfall_memory,
)


def _init_test_git_repo(repo_dir: Path) -> str:
    """Helper to initialize a real git repository with an initial commit."""
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "TestUser"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    test_file = repo_dir / "README.md"
    test_file.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip()


def test_evaluate_repo_sync_policy_non_git(tmp_path: Path) -> None:
    non_git_dir = tmp_path / "plain_dir"
    non_git_dir.mkdir()

    decision = evaluate_repo_sync_policy(non_git_dir)
    assert isinstance(decision, RepoSyncDecision)
    assert decision.sync_recommended is False
    assert decision.reason in ("not_a_git_repo", "unsupported_not_git_repo")
    assert decision.current_head == ""
    assert decision.is_dirty is False


def test_evaluate_repo_sync_policy_missing_git_cli(tmp_path: Path) -> None:
    git_dir = tmp_path / "mock_git"
    git_dir.mkdir()
    (git_dir / ".git").mkdir()

    with patch("shutil.which", return_value=None):
        decision = evaluate_repo_sync_policy(git_dir)
        assert isinstance(decision, RepoSyncDecision)
        assert decision.sync_recommended is False
        assert decision.reason in ("git_not_available", "unsupported_git_cli_missing")


def test_evaluate_repo_sync_policy_initial_baseline(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo1"
    repo_dir.mkdir()
    head_commit = _init_test_git_repo(repo_dir)

    # When baseline_commit is None or whitespace, recommend initial sync
    decision = evaluate_repo_sync_policy(repo_dir, baseline_commit=None)
    assert isinstance(decision, RepoSyncDecision)
    assert decision.sync_recommended is True
    assert decision.reason == "initial_baseline"
    assert decision.current_head == head_commit
    assert decision.baseline_commit is None
    assert decision.is_dirty is False

    decision_empty_str = evaluate_repo_sync_policy(repo_dir, baseline_commit="   ")
    assert decision_empty_str.sync_recommended is True
    assert decision_empty_str.reason == "initial_baseline"


def test_evaluate_repo_sync_policy_in_sync(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo2"
    repo_dir.mkdir()
    head_commit = _init_test_git_repo(repo_dir)

    decision = evaluate_repo_sync_policy(repo_dir, baseline_commit=head_commit)
    assert isinstance(decision, RepoSyncDecision)
    assert decision.sync_recommended is False
    assert decision.reason in ("in_sync", "up_to_date")
    assert decision.ahead_commits_count == 0
    assert decision.is_dirty is False
    assert len(decision.files_changed) == 0


def test_evaluate_repo_sync_policy_uncommitted_changes(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo3"
    repo_dir.mkdir()
    head_commit = _init_test_git_repo(repo_dir)

    # Introduce uncommitted dirty file
    dirty_file = repo_dir / "dirty_script.py"
    dirty_file.write_text("print('hello')", encoding="utf-8")

    decision = evaluate_repo_sync_policy(
        repo_dir, baseline_commit=head_commit, include_uncommitted=True
    )
    assert isinstance(decision, RepoSyncDecision)
    assert decision.sync_recommended is True
    assert decision.is_dirty is True
    assert decision.reason == "uncommitted_changes"
    assert "dirty_script.py" in decision.files_changed


def test_evaluate_repo_sync_policy_commits_ahead(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo4"
    repo_dir.mkdir()
    base_commit = _init_test_git_repo(repo_dir)

    # Add a second commit
    feature_file = repo_dir / "feature.py"
    feature_file.write_text("# Feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.py"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Add feature"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    decision = evaluate_repo_sync_policy(repo_dir, baseline_commit=base_commit, commit_threshold=1)
    assert isinstance(decision, RepoSyncDecision)
    assert decision.sync_recommended is True
    assert decision.reason in ("commits_ahead", "commit_threshold_exceeded")
    assert decision.ahead_commits_count == 1
    assert "feature.py" in decision.files_changed


def test_evaluate_repo_sync_policy_diverged_history(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo5"
    repo_dir.mkdir()
    _init_test_git_repo(repo_dir)

    # Use a non-ancestor dummy hash
    fake_baseline = "0123456789abcdef0123456789abcdef01234567"
    decision = evaluate_repo_sync_policy(repo_dir, baseline_commit=fake_baseline)
    assert isinstance(decision, RepoSyncDecision)
    assert decision.sync_recommended is True
    assert decision.reason in ("diverged_or_rebased_history", "baseline_diverged_or_shallow")
    assert decision.ahead_commits_count == -1


def test_create_pitfall_memory_success() -> None:
    memory = create_pitfall_memory(
        content="Docker in-container network binding failed on 0.0.0.0:8080 due to permission deny",
        failure_reason="Rootless container cannot bind privileged ports without CAP_NET_BIND_SERVICE",
        negative_lesson="Do not attempt binding ports < 1024 or host loopback inside non-root execution sandbox",
        subtask_phase="verify",
        confidence_tier="strong",
        relation_category="same_problem",
        importance=0.9,
        related_entities=["Docker", "Sandbox"],
        source_chat_id="chat-123",
        source_message_id="msg-456",
    )

    assert isinstance(memory, EpisodicMemory)
    assert memory.is_failure_attempt is True
    assert memory.failure_reason == "Rootless container cannot bind privileged ports without CAP_NET_BIND_SERVICE"
    assert "Do not attempt" in (memory.negative_lesson or "")
    assert memory.subtask_phase == "verify"
    assert memory.confidence_tier == "strong"
    assert memory.relation_category == "same_problem"
    assert memory.importance == 0.9
    assert memory.related_entities == ["Docker", "Sandbox"]
    assert memory.source_chat_id == "chat-123"


def test_create_pitfall_memory_validation_errors() -> None:
    with pytest.raises(ValueError, match="content"):
        create_pitfall_memory(
            content="   ",
            failure_reason="reason",
            negative_lesson="lesson",
        )

    with pytest.raises(ValueError, match="failure_reason"):
        create_pitfall_memory(
            content="valid content",
            failure_reason="",
            negative_lesson="lesson",
        )

    with pytest.raises(ValueError, match="negative_lesson"):
        create_pitfall_memory(
            content="valid content",
            failure_reason="valid reason",
            negative_lesson="  \n\t ",
        )


def test_create_pitfall_memory_importance_clamping() -> None:
    mem_high = create_pitfall_memory(
        content="content",
        failure_reason="reason",
        negative_lesson="lesson",
        importance=1.5,
    )
    assert mem_high.importance == 1.0

    mem_low = create_pitfall_memory(
        content="content",
        failure_reason="reason",
        negative_lesson="lesson",
        importance=-0.5,
    )
    assert mem_low.importance == 0.0

"""Unit tests for GitRepoDigestExtractor."""

from pathlib import Path

from myrm_agent_harness.toolkits.code_execution.git_digest import (
    RepoCommitItem,
    RepoHistoryEvidenceDigest,
    extract_repo_history_digest,
)


def test_extract_repo_history_digest_non_git(tmp_path: Path) -> None:
    digest = extract_repo_history_digest(tmp_path)
    assert isinstance(digest, RepoHistoryEvidenceDigest)
    assert digest.current_branch == "none"
    assert digest.is_dirty is False
    assert len(digest.recent_commits) == 0


def test_extract_repo_history_digest_current_workspace() -> None:
    # We are in a git workspace under open-perplexity monorepo
    repo_root = Path.cwd()
    digest = extract_repo_history_digest(repo_root, max_commits=3)

    assert isinstance(digest, RepoHistoryEvidenceDigest)
    assert digest.repo_name in ("open-perplexity", "myrm-agent", "myrm-agent-harness")
    assert digest.current_branch in ("main", "HEAD", "master")
    assert digest.total_commits_examined > 0
    assert len(digest.recent_commits) > 0

    first_commit = digest.recent_commits[0]
    assert isinstance(first_commit, RepoCommitItem)
    assert len(first_commit.commit_hash) == 40
    assert len(first_commit.short_hash) == 8
    assert bool(first_commit.author)
    assert bool(first_commit.subject)


def test_evaluate_repo_sync_policy_non_git(tmp_path: Path) -> None:
    from myrm_agent_harness.toolkits.code_execution.git_digest import (
        RepoSyncDecision,
        evaluate_repo_sync_policy,
    )

    decision = evaluate_repo_sync_policy(tmp_path, baseline_commit=None)
    assert isinstance(decision, RepoSyncDecision)
    assert decision.should_sync is False
    assert decision.reason == "not_a_git_repo"


def test_evaluate_repo_sync_policy_initial_baseline() -> None:
    from myrm_agent_harness.toolkits.code_execution.git_digest import evaluate_repo_sync_policy

    repo_root = Path.cwd()
    decision = evaluate_repo_sync_policy(repo_root, baseline_commit=None)
    assert decision.should_sync is True
    assert decision.reason == "initial_baseline"
    assert bool(decision.current_head)


def test_evaluate_repo_sync_policy_up_to_date(tmp_path: Path) -> None:
    import subprocess
    from myrm_agent_harness.toolkits.code_execution.git_digest import evaluate_repo_sync_policy

    repo_dir = tmp_path / "clean_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True, capture_output=True)
    (repo_dir / "init.txt").write_text("ok", encoding="utf-8")
    subprocess.run(["git", "add", "init.txt"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True, capture_output=True)

    init_decision = evaluate_repo_sync_policy(repo_dir, baseline_commit=None)
    head = init_decision.current_head
    assert bool(head)

    # Evaluate with current head as baseline in a clean repository
    decision = evaluate_repo_sync_policy(repo_dir, baseline_commit=head)
    assert decision.should_sync is False
    assert decision.reason in ("up_to_date", "in_sync")
    assert decision.commits_behind == 0
    assert decision.baseline_valid is True


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
    # We are in open-perplexity git workspace
    repo_root = Path.cwd()
    digest = extract_repo_history_digest(repo_root, max_commits=3)

    assert isinstance(digest, RepoHistoryEvidenceDigest)
    assert digest.repo_name == "open-perplexity"
    assert digest.current_branch in ("main", "HEAD", "master")
    assert digest.total_commits_examined > 0
    assert len(digest.recent_commits) > 0

    first_commit = digest.recent_commits[0]
    assert isinstance(first_commit, RepoCommitItem)
    assert len(first_commit.commit_hash) == 40
    assert len(first_commit.short_hash) == 8
    assert bool(first_commit.author)
    assert bool(first_commit.subject)

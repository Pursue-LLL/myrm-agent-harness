"""Unit tests for zero-subprocess Git metadata resolver."""

import time
from pathlib import Path

from myrm_agent_harness.infra.git.git_resolver import (
    resolve_git_branch,
    resolve_git_metadata,
)


def test_resolve_git_metadata_standard_repo(tmp_path: Path):
    """Test resolving metadata from a standard .git directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git_dir = repo / ".git"
    git_dir.mkdir()

    # Create HEAD pointing to main
    head_file = git_dir / "HEAD"
    head_file.write_text("ref: refs/heads/main\n", encoding="utf-8")

    # Create refs/heads/main commit hash
    refs_heads = git_dir / "refs" / "heads"
    refs_heads.mkdir(parents=True)
    commit_sha = "a" * 40
    (refs_heads / "main").write_text(f"{commit_sha}\n", encoding="utf-8")

    meta = resolve_git_metadata(repo)
    assert meta.branch == "main"
    assert meta.commit == commit_sha
    assert not meta.is_worktree
    assert not meta.is_detached

    assert resolve_git_branch(repo) == "main"


def test_resolve_git_metadata_linked_worktree(tmp_path: Path):
    """Test resolving metadata when .git is a file pointing to a gitdir (Linked Worktree)."""
    main_git = tmp_path / "main_repo" / ".git" / "worktrees" / "wt1"
    main_git.mkdir(parents=True)
    head_file = main_git / "HEAD"
    head_file.write_text("ref: refs/heads/feature-worktree\n", encoding="utf-8")

    wt_repo = tmp_path / "worktree_dir"
    wt_repo.mkdir()
    git_file = wt_repo / ".git"
    git_file.write_text(f"gitdir: {main_git}\n", encoding="utf-8")

    meta = resolve_git_metadata(wt_repo)
    assert meta.branch == "feature-worktree"
    assert meta.is_worktree is True
    assert meta.is_detached is False
    assert resolve_git_branch(wt_repo) == "feature-worktree"


def test_resolve_git_metadata_detached_head(tmp_path: Path):
    """Test resolving metadata in detached HEAD state."""
    repo = tmp_path / "detached_repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)

    commit_sha = "0123456789abcdef0123456789abcdef01234567"
    (git_dir / "HEAD").write_text(f"{commit_sha}\n", encoding="utf-8")

    meta = resolve_git_metadata(repo)
    assert meta.commit == commit_sha
    assert meta.branch == "(detached:0123456)"
    assert meta.is_detached is True
    assert resolve_git_branch(repo) == "(detached:0123456)"


def test_resolve_git_metadata_packed_refs(tmp_path: Path):
    """Test resolving commit from packed-refs file."""
    repo = tmp_path / "packed_repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)

    (git_dir / "HEAD").write_text("ref: refs/heads/release/v1.0\n", encoding="utf-8")
    packed_sha = "b" * 40
    packed_content = (
        "# pack-refs with: peeled-tags\n"
        f"{packed_sha} refs/heads/release/v1.0\n"
        "c" * 40 + " refs/heads/other\n"
    )
    (git_dir / "packed-refs").write_text(packed_content, encoding="utf-8")

    meta = resolve_git_metadata(repo)
    assert meta.branch == "release/v1.0"
    assert meta.commit == packed_sha


def test_resolve_git_metadata_not_a_git_repo(tmp_path: Path):
    """Test resolving in a directory without .git returns empty metadata."""
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()

    meta = resolve_git_metadata(plain_dir)
    assert meta.branch is None
    assert meta.commit is None
    assert resolve_git_branch(plain_dir) is None


def test_resolve_git_metadata_mtime_caching(tmp_path: Path):
    """Test that mtime caching avoids re-reading files when unchanged."""
    repo = tmp_path / "cache_repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    head_file = git_dir / "HEAD"
    head_file.write_text("ref: refs/heads/branch-1\n", encoding="utf-8")

    meta1 = resolve_git_metadata(repo)
    assert meta1.branch == "branch-1"

    # Reading again immediately should return cached metadata
    meta2 = resolve_git_metadata(repo)
    assert meta2 is meta1

    # Modify HEAD and update mtime to bust cache
    time.sleep(0.01)
    head_file.write_text("ref: refs/heads/branch-2\n", encoding="utf-8")
    # Touch mtime forward
    new_mtime = head_file.stat().st_mtime + 2.0
    import os

    os.utime(head_file, (new_mtime, new_mtime))

    meta3 = resolve_git_metadata(repo)
    assert meta3.branch == "branch-2"


def test_resolve_git_metadata_permission_or_os_error(tmp_path: Path):
    """Test that file read errors (e.g. unreadable HEAD) degrade gracefully without throwing."""
    repo = tmp_path / "corrupt_repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    head_file = git_dir / "HEAD"
    head_file.mkdir()  # Making HEAD a directory causes OSError / IsADirectoryError on read_text

    meta = resolve_git_metadata(repo)
    assert meta.branch is None
    assert meta.commit is None
    assert resolve_git_branch(repo) is None


def test_resolve_git_metadata_empty_head(tmp_path: Path):
    """Test that an empty HEAD file returns empty metadata without throwing."""
    repo = tmp_path / "empty_head_repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    head_file = git_dir / "HEAD"
    head_file.write_text("   \n", encoding="utf-8")

    meta = resolve_git_metadata(repo)
    assert meta.branch is None
    assert meta.commit is None


def test_resolve_git_metadata_relative_worktree_and_cache_eviction(tmp_path: Path):
    """Test linked worktree with relative path and LRU cache eviction limit."""
    from myrm_agent_harness.infra.git.git_resolver import _CACHE_LOCK, _METADATA_CACHE

    main_git = tmp_path / "main_repo" / ".git" / "worktrees" / "wt_rel"
    main_git.mkdir(parents=True)
    (main_git / "HEAD").write_text("ref: refs/heads/rel-branch\n", encoding="utf-8")

    wt_repo = tmp_path / "worktree_rel_dir"
    wt_repo.mkdir()
    rel_path = Path("..") / "main_repo" / ".git" / "worktrees" / "wt_rel"
    (wt_repo / ".git").write_text(f"gitdir: {rel_path}\n", encoding="utf-8")

    meta = resolve_git_metadata(wt_repo)
    assert meta.branch == "rel-branch"
    assert meta.is_worktree is True

    # Test cache capacity eviction (> 64)
    with _CACHE_LOCK:
        _METADATA_CACHE.clear()
        for i in range(70):
            _METADATA_CACHE[f"fake_key_{i}"] = (0.0, meta)

    # Resolving now triggers cache clear and insertion
    resolve_git_metadata(wt_repo)
    with _CACHE_LOCK:
        assert len(_METADATA_CACHE) <= 64



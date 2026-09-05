"""Repository History Evidence Digest Extractor.

Extracts mechanical commit logs, branch information, and recent change digests
from a git repository in milliseconds (<50ms) using git CLI or graceful fallbacks.

[INPUT]
- repo_path: str | Path to target git repository
- max_commits: int = 5 (recent commits to summarize)

[OUTPUT]
- RepoCommitItem: Single commit summary item (hash, author, timestamp, message, files_changed)
- RepoHistoryEvidenceDigest: Strong-typed snapshot of repository recent history
- extract_repo_history_digest: Pure function extracting repo evidence digest

[POS]
Harness framework code_execution layer.
100% deterministic, zero LLM cost, non-blocking with 2s timeout bounds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from pathlib import Path
import shutil
import subprocess

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepoCommitItem:
    """Compact summary of a single git commit."""

    commit_hash: str
    short_hash: str
    author: str
    committed_at: str
    subject: str
    files_changed: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RepoHistoryEvidenceDigest:
    """Strong-typed repository history and change evidence digest."""

    repo_name: str
    repo_path: str
    current_branch: str
    is_dirty: bool
    recent_commits: tuple[RepoCommitItem, ...] = field(default_factory=tuple)
    total_commits_examined: int = 0
    extracted_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class RepoSyncDecision:
    """Decision output for incremental repository synchronization policy."""

    repo_path: str
    current_head: str
    baseline_commit: str | None
    is_dirty: bool
    sync_recommended: bool
    ahead_commits_count: int
    reason: str
    files_changed: tuple[str, ...] = field(default_factory=tuple)


def _run_git_cmd(
    args: list[str], cwd: Path, timeout: float = 2.0
) -> tuple[int, str]:
    """Execute git subcommands safely with tight timeout."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd)] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.debug("Git command %s in %s failed: %s", args, cwd, exc)
        return -1, ""


def extract_repo_history_digest(
    repo_path: str | Path,
    *,
    max_commits: int = 5,
) -> RepoHistoryEvidenceDigest:
    """Extract structured repository history digest from a local git workspace.

    Args:
        repo_path: Path to the git workspace or repository root.
        max_commits: Maximum number of recent commits to extract.

    Returns:
        Structured RepoHistoryEvidenceDigest.
    """
    path = Path(repo_path).resolve()
    repo_name = path.name

    if not path.is_dir() or not (path / ".git").exists():
        return RepoHistoryEvidenceDigest(
            repo_name=repo_name,
            repo_path=str(path),
            current_branch="none",
            is_dirty=False,
            recent_commits=(),
            total_commits_examined=0,
        )

    if not shutil.which("git"):
        return RepoHistoryEvidenceDigest(
            repo_name=repo_name,
            repo_path=str(path),
            current_branch="unknown",
            is_dirty=False,
            recent_commits=(),
            total_commits_examined=0,
        )

    # 1. Probe branch
    rc_branch, branch_str = _run_git_cmd(["rev-parse", "--abbrev-ref", "HEAD"], path)
    current_branch = branch_str if rc_branch == 0 and branch_str else "HEAD"

    # 2. Probe dirty status
    rc_status, status_str = _run_git_cmd(["status", "--porcelain"], path)
    is_dirty = bool(status_str) if rc_status == 0 else False

    # 3. Extract recent commits with custom delimiter
    # Format: hash%x1fauthor%x1fdate%x1fsubject
    fmt = "%H%x1f%an%x1f%aI%x1f%s"
    rc_log, log_str = _run_git_cmd(
        [
            "log",
            f"-n{max_commits}",
            "--no-merges",
            f"--pretty=format:{fmt}",
        ],
        path,
    )

    commits: list[RepoCommitItem] = []
    if rc_log == 0 and log_str:
        for line in log_str.splitlines():
            parts = line.split("\x1f")
            if len(parts) >= 4:
                full_hash, author, date_str, subject = parts[0], parts[1], parts[2], parts[3]
                short_hash = full_hash[:8]

                # Get files changed for this commit (<50ms for single commit)
                rc_files, files_out = _run_git_cmd(
                    ["diff-tree", "--no-commit-id", "--name-only", "-r", full_hash],
                    path,
                    timeout=1.0,
                )
                changed_files = (
                    tuple(files_out.splitlines()[:10])
                    if rc_files == 0 and files_out
                    else ()
                )

                commits.append(
                    RepoCommitItem(
                        commit_hash=full_hash,
                        short_hash=short_hash,
                        author=author,
                        committed_at=date_str,
                        subject=subject,
                        files_changed=changed_files,
                    )
                )

    return RepoHistoryEvidenceDigest(
        repo_name=repo_name,
        repo_path=str(path),
        current_branch=current_branch,
        is_dirty=is_dirty,
        recent_commits=tuple(commits),
        total_commits_examined=len(commits),
    )

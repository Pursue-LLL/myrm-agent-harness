"""Local git auto-commit for wiki vault directories.

[INPUT]
- myrm_agent_harness.toolkits.wiki.core.structure::WikiStructure (POS: vault layout)
- myrm_agent_harness.toolkits.wiki.core.config::WikiConfig (POS: version control knobs)

[OUTPUT]
- commit_vault_git_snapshot: Initialize repo if needed and commit vault changes
- maybe_commit_vault_git_snapshot: Gate on WikiConfig.enable_version_control

[POS]
Framework-level vault version discipline for Karpathy/Obsidian users who expect git log/blame.
Uses a real .git inside the vault base_dir (not shadow git).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_VAULT_GITIGNORE = """# Myrm wiki vault — auto-managed
**/.metadata.json
wiki/.metadata.json
*.sqlite
*.sqlite3
*.db
__pycache__/
.DS_Store
Thumbs.db
"""

_GIT_AUTHOR_NAME = "Myrm"
_GIT_AUTHOR_EMAIL = "myrm@local"


@dataclass(frozen=True, slots=True)
class VaultGitCommitResult:
    committed: bool
    commit_hash: str | None = None
    skipped_reason: str | None = None


def _run_git(vault_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(vault_dir), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _git_available() -> bool:
    return shutil.which("git") is not None


def _ensure_repo(vault_dir: Path) -> None:
    git_dir = vault_dir / ".git"
    if not git_dir.exists():
        _run_git(vault_dir, "init", "--initial-branch=main")
        _run_git(vault_dir, "config", "user.name", _GIT_AUTHOR_NAME)
        _run_git(vault_dir, "config", "user.email", _GIT_AUTHOR_EMAIL)

    gitignore_path = vault_dir / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(_VAULT_GITIGNORE, encoding="utf-8")


def _has_staged_changes(vault_dir: Path) -> bool:
    head = _run_git(vault_dir, "rev-parse", "--verify", "HEAD", check=False)
    if head.returncode != 0:
        status = _run_git(vault_dir, "status", "--porcelain")
        return bool(status.stdout.strip())
    diff = _run_git(vault_dir, "diff-index", "--cached", "--quiet", "HEAD", check=False)
    return diff.returncode != 0


def commit_vault_git_snapshot(
    structure: WikiStructure,
    *,
    reason: str,
) -> VaultGitCommitResult:
    """Commit current vault tree when git is available and files changed."""
    if not _git_available():
        return VaultGitCommitResult(committed=False, skipped_reason="git_unavailable")

    vault_dir = structure.base_dir.resolve()
    if not vault_dir.is_dir():
        return VaultGitCommitResult(committed=False, skipped_reason="vault_missing")

    try:
        _ensure_repo(vault_dir)
        _run_git(vault_dir, "add", "-A")
        if not _has_staged_changes(vault_dir):
            return VaultGitCommitResult(committed=False, skipped_reason="no_changes")

        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        message = f"myrm: {reason}\n\ntimestamp={timestamp}"
        commit = _run_git(
            vault_dir,
            "commit",
            "-m",
            message,
            "--no-gpg-sign",
            "--no-verify",
        )
        _ = commit.stdout
        rev = _run_git(vault_dir, "rev-parse", "HEAD")
        commit_hash = rev.stdout.strip()
        logger.info("Wiki vault git snapshot committed (%s): %s", reason, commit_hash)
        return VaultGitCommitResult(committed=True, commit_hash=commit_hash)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or exc.stdout or "").strip()
        logger.warning("Wiki vault git snapshot failed (%s): %s", reason, stderr)
        return VaultGitCommitResult(committed=False, skipped_reason="git_error")


def maybe_commit_vault_git_snapshot(
    structure: WikiStructure,
    config: WikiConfig,
    *,
    reason: str,
) -> VaultGitCommitResult:
    """Commit vault snapshot when version control is enabled in WikiConfig."""
    if not config.enable_version_control:
        return VaultGitCommitResult(committed=False, skipped_reason="disabled")
    return commit_vault_git_snapshot(structure, reason=reason)

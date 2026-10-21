"""Isolated Commit Guard — Safe git commits skipping hooks on isolated worktrees.

Defends against automated checkpoint commits hanging or failing when a user's
repository defines custom git hooks (e.g. husky, lint-staged, pre-commit) that
depend on missing node_modules or interactive confirmations in isolated worktrees.
Aligned with teamai-cli PR #422 production practice.

[INPUT]
- cwd: Repository or worktree working directory
- message: Commit message
- paths: Optional paths to commit specifically
- intent: CommitIntent differentiating internal automation from user explicit commits

[OUTPUT]
- CommitIntent: Enum categorizing commit purpose
- CommitResult: Structured execution report
- run_isolated_commit: Safe commit executor with --no-verify and deadlock protection
- build_commit_args: Command line argument builder
- build_isolated_commit_env: Subprocess environment injector with HUSKY=0
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
import os
from pathlib import Path
import subprocess
import time
from typing import Mapping, Sequence

logger = logging.getLogger(__name__)

_DEFAULT_COMMIT_TIMEOUT_SECONDS: int = 30


class CommitIntent(str, Enum):
    """Categorizes the initiator and purpose of a git commit."""

    ISOLATED_CHECKPOINT = "isolated_checkpoint"
    INTERNAL_SYNC = "internal_sync"
    USER_EXPLICIT_COMMIT = "user_explicit_commit"


@dataclass(frozen=True, slots=True)
class CommitResult:
    """Detailed execution result of a git commit attempt."""

    success: bool
    commit_hash: str | None
    skipped_hooks: bool
    output: str
    error: str | None
    duration_ms: float


def should_skip_hooks(intent: CommitIntent) -> bool:
    """Determine whether a commit should skip git hooks via --no-verify."""
    return intent in (CommitIntent.ISOLATED_CHECKPOINT, CommitIntent.INTERNAL_SYNC)


def build_commit_args(
    message: str,
    paths: Sequence[str] | None = None,
    *,
    skip_hooks: bool = True,
) -> list[str]:
    """Construct git commit argument list honoring hook skip policy and path specs.

    Args:
        message: Commit log message.
        paths: Specific paths to commit, if any.
        skip_hooks: If True, adds --no-verify.

    Returns:
        List of command-line arguments for git.
    """
    if paths is None:
        args = ["commit"]
        if skip_hooks:
            args.append("--no-verify")
        args.extend(["-m", message])
        return args

    # Path-restricted commit uses --literal-pathspecs to avoid glob misinterpretations
    args = ["--literal-pathspecs", "commit"]
    if skip_hooks:
        args.append("--no-verify")
    args.extend(["-m", message, "--", *paths])
    return args


def build_isolated_commit_env(
    base_env: Mapping[str, str] | None = None,
    *,
    skip_hooks: bool = True,
) -> dict[str, str]:
    """Build isolated environment variables to prevent hooks from firing in child processes.

    Injects HUSKY=0 and PRE_COMMIT_ALLOW_NO_CONFIG=1 when skip_hooks=True.
    """
    env = os.environ.copy() if base_env is None else dict(base_env)
    if skip_hooks:
        env["HUSKY"] = "0"
        env["PRE_COMMIT_ALLOW_NO_CONFIG"] = "1"
    return env


def run_isolated_commit(
    cwd: str | Path,
    message: str,
    paths: Sequence[str] | None = None,
    *,
    intent: CommitIntent = CommitIntent.ISOLATED_CHECKPOINT,
    timeout_seconds: int = _DEFAULT_COMMIT_TIMEOUT_SECONDS,
) -> CommitResult:
    """Execute a git commit with hook-skipping guard on isolated checkpoints.

    Args:
        cwd: Directory path of the repository or worktree.
        message: Commit message.
        paths: Specific paths to commit (without affecting other staged files).
        intent: CommitIntent indicating whether hooks should be bypassed.
        timeout_seconds: Timeout threshold to avoid deadlock on interactive hooks.

    Returns:
        CommitResult with commit hash and status.
    """
    target_dir = str(cwd)
    skip_hooks = should_skip_hooks(intent)
    args = ["git", *build_commit_args(message, paths, skip_hooks=skip_hooks)]
    env = build_isolated_commit_env(skip_hooks=skip_hooks)

    start_t = time.perf_counter()
    try:
        proc = subprocess.run(
            args,
            cwd=target_dir,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
        )
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0

        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or proc.stdout.strip()
            logger.warning(
                "Git commit failed in %s (intent=%s, skip_hooks=%s, rc=%d): %s",
                target_dir,
                intent.value,
                skip_hooks,
                proc.returncode,
                err_msg,
            )
            return CommitResult(
                success=False,
                commit_hash=None,
                skipped_hooks=skip_hooks,
                output=proc.stdout.strip(),
                error=err_msg,
                duration_ms=elapsed_ms,
            )

        # Retrieve newly minted commit hash
        hash_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        commit_hash = hash_proc.stdout.strip() if hash_proc.returncode == 0 else None

        logger.info(
            "Git commit succeeded in %s: %s (intent=%s, skip_hooks=%s)",
            target_dir,
            (commit_hash[:10] if commit_hash else "ok"),
            intent.value,
            skip_hooks,
        )
        return CommitResult(
            success=True,
            commit_hash=commit_hash,
            skipped_hooks=skip_hooks,
            output=proc.stdout.strip(),
            error=None,
            duration_ms=elapsed_ms,
        )

    except subprocess.TimeoutExpired:
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        err_msg = (
            f"Git commit timed out after {timeout_seconds}s in {target_dir}. "
            "Possible un-isolated git hook deadlock."
        )
        logger.error(err_msg)
        return CommitResult(
            success=False,
            commit_hash=None,
            skipped_hooks=skip_hooks,
            output="",
            error=err_msg,
            duration_ms=elapsed_ms,
        )

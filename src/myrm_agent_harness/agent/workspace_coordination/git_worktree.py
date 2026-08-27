"""Git worktree physical isolation for concurrent subagents.

[INPUT]
- parent_workspace: str | Path | None - root path of parent workspace
- subagent_id: str | None - unique identifier for child subagent

[OUTPUT]
- create_subagent_worktree: Create lightweight git worktree branch for subagent
- finalize_subagent_worktree: Inspect commits/dirty state and auto-prune clean worktrees
- resolve_repo_root: Resolve git top-level root for a workspace path
- build_worktree_context_note: Instruction block appended to subagent prompt

[POS]
High-performance subagent workspace isolation. Eliminates file copy overhead (100x faster)
and guarantees isolated git branches for concurrent writers on git-backed workspaces.
Degrades gracefully to directory isolation for non-git workspaces.
"""

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_GIT_TIMEOUT: int = 30
_WORKTREES_DIRNAME: str = ".worktrees"
_BRANCH_NAMESPACE: str = "myrm-subagent"


def _run_git(args: list[str], cwd: str, timeout: int = _GIT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run a git command, capturing text output safely without raising on non-zero exit."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def resolve_repo_root(path: str | Path | None) -> str | None:
    """Return the git toplevel directory for path, or None if not inside a git repository."""
    if not path:
        return None
    try:
        candidate = os.path.abspath(os.path.expanduser(str(path)))
    except Exception:
        return None
    if not os.path.isdir(candidate):
        return None
    try:
        result = _run_git(["rev-parse", "--show-toplevel"], cwd=candidate)
    except Exception as exc:
        logger.debug("git worktree: rev-parse failed: %s", exc)
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return root or None


def _ensure_gitignore_entry(repo_root: str) -> None:
    """Ensure .worktrees/ is ignored in the parent repository .gitignore."""
    gitignore = Path(repo_root) / ".gitignore"
    entry = f"{_WORKTREES_DIRNAME}/"
    try:
        existing = (
            gitignore.read_text(encoding="utf-8-sig", errors="replace")
            if gitignore.exists()
            else ""
        )
        if entry not in existing.splitlines():
            with open(gitignore, "a", encoding="utf-8") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write(f"{entry}\n")
    except Exception as exc:
        logger.debug("git worktree: could not update .gitignore: %s", exc)


def create_subagent_worktree(
    parent_workspace: str | Path | None,
    subagent_id: str | None = None,
) -> dict[str, str] | None:
    """Create an isolated git worktree for a child agent.

    Returns metadata (path, branch, repo_root, base_commit) on success,
    or None when workspace is not a git repository or worktree creation fails.
    """
    repo_root = resolve_repo_root(parent_workspace)
    if not repo_root:
        return None

    short_id = (subagent_id or uuid.uuid4().hex[:8]).replace("/", "-")
    wt_name = f"subagent-{short_id}"
    branch = f"{_BRANCH_NAMESPACE}/{wt_name}"
    wt_path = Path(repo_root) / _WORKTREES_DIRNAME / wt_name

    try:
        wt_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("git worktree: cannot create directory %s: %s", wt_path.parent, exc)
        return None

    _ensure_gitignore_entry(repo_root)

    try:
        base = _run_git(["rev-parse", "HEAD"], cwd=repo_root)
        base_commit = base.stdout.strip() if base.returncode == 0 else ""
        result = _run_git(
            ["worktree", "add", str(wt_path), "-b", branch, "HEAD"],
            cwd=repo_root,
        )
    except Exception as exc:
        logger.warning("git worktree: creation failed: %s", exc)
        return None

    if result.returncode != 0:
        logger.warning("git worktree: add failed (%s): %s", result.returncode, result.stderr.strip())
        return None

    logger.info("Subagent git worktree created: %s (branch: %s)", wt_path, branch)
    return {
        "path": str(wt_path),
        "branch": branch,
        "repo_root": repo_root,
        "base_commit": base_commit,
    }


def mark_worktree_payload_unproven(
    payload: dict[str, object],
    reason: str,
    *,
    unmeasured: str = "commits/dirty",
) -> dict[str, object]:
    """Flag a worktree result payload as un-inspected when git inspection fails."""
    path = payload.get("path", "")
    branch = payload.get("branch", "")
    payload["inspection_failed"] = True
    payload["note"] = (
        f"Git inspection failed ({reason}): {unmeasured} unproven. "
        f"The worktree at {path} (branch {branch}) was preserved for review."
    )
    logger.warning("git worktree: probe failed (%s) - preserved %s", reason, path)
    return payload


def finalize_subagent_worktree(
    info: dict[str, str],
    *,
    prune: bool = True,
) -> dict[str, object]:
    """Inspect and optionally prune a subagent worktree after task completion.

    Clean worktrees with 0 new commits and clean status are auto-pruned.
    Worktrees with changes are preserved for parent agent review.
    """
    path = info.get("path", "")
    branch = info.get("branch", "")
    repo_root = info.get("repo_root", "")
    base_commit = info.get("base_commit", "")

    payload: dict[str, object] = {
        "path": path,
        "branch": branch,
        "commits": 0,
        "dirty": False,
        "pruned": False,
    }

    if not path or not os.path.isdir(path):
        payload["pruned"] = True
        return payload

    if not base_commit:
        return mark_worktree_payload_unproven(payload, "no base_commit recorded", unmeasured="commits")

    failed: list[str] = []
    unmeasured: list[str] = []

    try:
        counted = _run_git(["rev-list", "--count", f"{base_commit}..HEAD"], cwd=path)
        if counted.returncode == 0:
            payload["commits"] = int(counted.stdout.strip() or 0)
        else:
            failed.append(f"rev-list: {counted.stderr.strip()[:100]}")
            unmeasured.append("commits")

        status = _run_git(["status", "--porcelain"], cwd=path)
        if status.returncode == 0:
            payload["dirty"] = bool(status.stdout.strip())
        else:
            failed.append(f"status: {status.stderr.strip()[:100]}")
            unmeasured.append("dirty")
    except Exception as exc:
        return mark_worktree_payload_unproven(payload, f"inspection exception: {exc}")

    if failed:
        return mark_worktree_payload_unproven(payload, "; ".join(failed), unmeasured="/".join(unmeasured))

    if prune and payload["commits"] == 0 and not payload["dirty"]:
        try:
            removed = _run_git(["worktree", "remove", "--force", path], cwd=repo_root or path)
            if removed.returncode == 0:
                _run_git(["branch", "-D", branch], cwd=repo_root or path)
                payload["pruned"] = True
                logger.info("Clean subagent git worktree pruned: %s", path)
            else:
                logger.debug("git worktree prune failed: %s", removed.stderr.strip())
        except Exception as exc:
            logger.debug("git worktree prune exception: %s", exc)

    return payload


def build_worktree_context_note(info: dict[str, str]) -> str:
    """Build instruction block informing the subagent of its isolated worktree branch."""
    wt_path = info.get("path", "")
    branch = info.get("branch", "")
    return (
        f"\n\n[WORKTREE ISOLATION] You are operating in an isolated git worktree at: {wt_path}\n"
        f"Dedicated branch: {branch}\n"
        "Perform all edits and commands within this directory. Commit changes to your branch when ready. "
        "Clean, uncommitted worktrees with no commits are pruned automatically."
    )

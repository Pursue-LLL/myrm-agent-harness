"""Base branch drift detector and safe rebase gate for long-running goals.

[INPUT]
- .types::Goal, GoalStatus, ContinuationDecision (POS: Goal data types)
- .protocols::GoalProvider (POS: Goal provider protocol)
- agent.middlewares._session_context::get_workspace_root (POS: Workspace root accessor)
- asyncio.subprocess / shlex / subprocess (POS: Safe Git execution within workspace)

[OUTPUT]
- check_git_drift_and_rebase: Detects upstream branch drift and performs safe rebase or pauses for human review.

[POS]
Implements long-running task baseline drift detection (step 6.5d in the guard chain).
Checks if the workspace is in a Git repository tracking an upstream branch.
If the branch is behind upstream commits, it performs a safe rebase with autostash.
If a rebase conflict occurs, it strictly executes `git rebase --abort` to preserve the workspace
intact and transitions to PAUSED with DRIFT_CONFLICT_HUMAN_ESCALATION to prevent code corruption.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .types import ContinuationDecision, GoalStatus

if TYPE_CHECKING:
    from .protocols import GoalProvider
    from .types import Goal

logger = logging.getLogger(__name__)

_DRIFT_REBASE_METADATA_KEY = "_last_git_drift_check"


@dataclass(frozen=True)
class GitDriftStatus:
    """Git workspace tracking and drift status."""

    is_git_repo: bool
    upstream: str | None = None
    behind_count: int = 0
    ahead_count: int = 0


async def _run_git_cmd(args: list[str], cwd: str) -> tuple[int, str, str]:
    """Execute git command safely without shell expansion."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        return proc.returncode or 0, stdout.decode().strip(), stderr.decode().strip()
    except Exception as e:
        logger.debug("Git command execution failed: %s %s", args, e)
        return -1, "", str(e)


async def inspect_git_drift(workspace_root: str) -> GitDriftStatus:
    """Inspect if repository has upstream branch and calculate commits behind."""
    # 1. Check if it's a git repo
    code, out, _ = await _run_git_cmd(["rev-parse", "--is-inside-work-tree"], workspace_root)
    if code != 0 or out != "true":
        return GitDriftStatus(is_git_repo=False)

    # 2. Check upstream branch name
    code, upstream, _ = await _run_git_cmd(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        workspace_root,
    )
    if code != 0 or not upstream:
        return GitDriftStatus(is_git_repo=True, upstream=None)

    # 3. Check commit distance: behind count
    code, behind_str, _ = await _run_git_cmd(
        ["rev-list", "--count", f"HEAD..{upstream}"],
        workspace_root,
    )
    behind = int(behind_str) if code == 0 and behind_str.isdigit() else 0

    # 4. Check commit distance: ahead count
    code, ahead_str, _ = await _run_git_cmd(
        ["rev-list", "--count", f"{upstream}..HEAD"],
        workspace_root,
    )
    ahead = int(ahead_str) if code == 0 and ahead_str.isdigit() else 0

    return GitDriftStatus(
        is_git_repo=True,
        upstream=upstream,
        behind_count=behind,
        ahead_count=ahead,
    )


async def check_git_drift_and_rebase(
    goal_provider: GoalProvider,
    goal: Goal,
) -> ContinuationDecision | None:
    """Detect upstream branch drift and perform safe rebase or pause on conflict.

    Returns:
        None if workspace is up to date, not in git, or rebase succeeded cleanly.
        ContinuationDecision with drift_pause verdict if rebase conflicts and requires escalation.
    """
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_workspace_root,
    )

    ws_root = get_workspace_root()
    if not ws_root:
        return None

    status = await inspect_git_drift(ws_root)
    if not status.is_git_repo or not status.upstream or status.behind_count <= 0:
        return None

    logger.info(
        "Goal %s: detected upstream branch drift (%d commit(s) behind %s)",
        goal.goal_id,
        status.behind_count,
        status.upstream,
    )

    # Attempt safe rebase with autostash to preserve unstaged/staged work
    rebase_code, stdout, stderr = await _run_git_cmd(
        ["rebase", "--autostash", status.upstream],
        ws_root,
    )

    if rebase_code == 0:
        logger.info(
            "Goal %s: successfully rebased onto %s (%d commits caught up)",
            goal.goal_id,
            status.upstream,
            status.behind_count,
        )
        await goal_provider.update_metadata(
            goal.goal_id,
            {
                _DRIFT_REBASE_METADATA_KEY: {
                    "upstream": status.upstream,
                    "rebased_commits": status.behind_count,
                    "status": "success",
                }
            },
        )
        return None

    # Rebase failed or encountered conflicts: STRICT 100% PRESERVATION via abort!
    logger.warning(
        "Goal %s: safe rebase encountered conflict/error; executing `git rebase --abort` to preserve workspace",
        goal.goal_id,
    )
    abort_code, _, abort_err = await _run_git_cmd(["rebase", "--abort"], ws_root)
    if abort_code != 0:
        logger.error(
            "Goal %s: failed to abort rebase cleanly: %s",
            goal.goal_id,
            abort_err,
        )

    escalation_reason = (
        f"Base branch drift conflict: {status.behind_count} commits behind {status.upstream}. "
        "Safe rebase failed with conflict; workspace cleanly preserved and rolled back. "
        "DRIFT_CONFLICT_HUMAN_ESCALATION required."
    )

    await goal_provider.update_metadata(
        goal.goal_id,
        {
            _DRIFT_REBASE_METADATA_KEY: {
                "upstream": status.upstream,
                "behind": status.behind_count,
                "status": "conflict_aborted",
                "details": f"{stdout}\n{stderr}",
            },
            "pause_reason": escalation_reason,
        },
    )
    await goal_provider.update_status(goal.goal_id, GoalStatus.PAUSED)

    return ContinuationDecision(
        should_continue=False,
        verdict="drift_pause",
        reason=escalation_reason,
        turns_used=goal.turns_used,
        max_turns=goal.budget.max_turns if goal.budget else None,
    )

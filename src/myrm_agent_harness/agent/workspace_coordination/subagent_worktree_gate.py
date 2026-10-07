"""Manages subagent worktree lifecycle, diff inspection, and review merge gates.

[INPUT]
- agent.workspace_coordination.worktree_types::MergePrecheckResult, MergeStrategy, SubagentReviewSummary,
  SubagentWorktreeMeta, WorktreeFileChange, WorktreeIsolationConfig, WorktreeMergeResult (POS: Types and
  models for worktree.)

[OUTPUT]
- SubagentWorktreeReviewMergeGate: Manages subagent worktree lifecycle, diff inspection, and review merge
  gates.

[POS]
Manages subagent worktree lifecycle, diff inspection, and review merge gates.
"""

# ============================================================================
# SubagentWorktreeReviewMergeGate (Item 151)
# Production-grade git worktree physical isolation manager, structured review
# summary generator, dry-run merge precheck, and atomic merge-cleanup gate.
# ============================================================================

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from pathlib import Path

from .worktree_types import (
    MergePrecheckResult,
    MergeStrategy,
    SubagentReviewSummary,
    SubagentWorktreeMeta,
    WorktreeFileChange,
    WorktreeIsolationConfig,
    WorktreeMergeResult,
)

logger = logging.getLogger(__name__)


class SubagentWorktreeReviewMergeGate:
    """Manages subagent worktree lifecycle, diff inspection, and review merge gates."""

    def __init__(self, config: WorktreeIsolationConfig | None = None) -> None:
        self.config: WorktreeIsolationConfig = config or WorktreeIsolationConfig()

    def _run_git(
        self,
        args: list[str],
        cwd: str,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Safely executes a git command capturing output without unhandled exceptions."""
        effective_timeout = timeout or self.config.git_timeout_seconds
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=effective_timeout,
        )

    def _ensure_gitignore(self, repo_root: str) -> None:
        """Ensures the temporary worktrees directory is ignored in parent .gitignore."""
        gitignore = Path(repo_root) / ".gitignore"
        entry = f"{self.config.worktrees_dirname}/"
        try:
            existing = gitignore.read_text(encoding="utf-8", errors="replace") if gitignore.exists() else ""
            if entry not in existing.splitlines():
                with open(gitignore, "a", encoding="utf-8") as f:
                    if existing and not existing.endswith("\n"):
                        f.write("\n")
                    f.write(f"{entry}\n")
        except Exception as exc:
            logger.debug("Failed to update .gitignore in %s: %s", repo_root, exc)

    def create_isolated_worktree(
        self,
        repo_root: str,
        subagent_id: str | None = None,
    ) -> SubagentWorktreeMeta:
        """Provisions an isolated git worktree branch for child subagent execution."""
        clean_root = os.path.abspath(os.path.expanduser(repo_root))
        if not os.path.isdir(clean_root):
            raise ValueError(f"Repository root directory does not exist: {clean_root}")

        rev_root = self._run_git(["rev-parse", "--show-toplevel"], cwd=clean_root)
        if rev_root.returncode != 0:
            raise ValueError(f"Target path is not a git repository: {clean_root}")

        actual_repo_root = rev_root.stdout.strip()
        short_id = (subagent_id or uuid.uuid4().hex[:8]).replace("/", "-")
        worktree_name = f"subagent-{short_id}"
        branch_name = f"{self.config.branch_namespace}/{worktree_name}"
        worktree_path = str(Path(actual_repo_root) / self.config.worktrees_dirname / worktree_name)

        Path(worktree_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_gitignore(actual_repo_root)

        base_res = self._run_git(["rev-parse", "HEAD"], cwd=actual_repo_root)
        base_commit = base_res.stdout.strip() if base_res.returncode == 0 else ""

        add_res = self._run_git(
            ["worktree", "add", worktree_path, "-b", branch_name, "HEAD"],
            cwd=actual_repo_root,
        )
        if add_res.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {add_res.stderr.strip()}")

        return SubagentWorktreeMeta(
            subagent_id=short_id,
            worktree_path=worktree_path,
            branch_name=branch_name,
            repo_root=actual_repo_root,
            base_commit=base_commit,
        )

    def inspect_worktree(self, meta: SubagentWorktreeMeta) -> SubagentReviewSummary:
        """Inspects subagent changes generating structured review summary and diff metrics."""
        wt_path = meta.worktree_path
        if not os.path.isdir(wt_path):
            return SubagentReviewSummary(
                subagent_id=meta.subagent_id,
                branch_name=meta.branch_name,
                worktree_path=wt_path,
                base_commit=meta.base_commit,
                head_commit="",
                commits_ahead=0,
                is_dirty=False,
            )

        head_res = self._run_git(["rev-parse", "HEAD"], cwd=wt_path)
        head_commit = head_res.stdout.strip() if head_res.returncode == 0 else ""

        # Count commits ahead of base
        count_res = self._run_git(
            ["rev-list", "--count", f"{meta.base_commit}..HEAD"],
            cwd=wt_path,
        )
        commits_ahead = int(count_res.stdout.strip() or 0) if count_res.returncode == 0 else 0

        # Retrieve commit messages
        log_res = self._run_git(
            ["log", "--oneline", f"{meta.base_commit}..HEAD"],
            cwd=wt_path,
        )
        commit_messages = [
            line.strip() for line in log_res.stdout.splitlines() if line.strip()
        ] if log_res.returncode == 0 else []

        # Check dirty uncommitted changes
        status_res = self._run_git(["status", "--porcelain"], cwd=wt_path)
        is_dirty = bool(status_res.stdout.strip())

        # Changed files list
        names_res = self._run_git(
            ["diff", "--name-only", f"{meta.base_commit}..HEAD"],
            cwd=wt_path,
        )
        changed_files = [
            line.strip() for line in names_res.stdout.splitlines() if line.strip()
        ] if names_res.returncode == 0 else []

        # Parse numstat insertions and deletions
        numstat_res = self._run_git(
            ["diff", "--numstat", f"{meta.base_commit}..HEAD"],
            cwd=wt_path,
        )
        file_changes: list[WorktreeFileChange] = []
        total_insertions = 0
        total_deletions = 0

        if numstat_res.returncode == 0:
            for line in numstat_res.stdout.splitlines():
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    ins_str, del_str, path_str = parts[0], parts[1], parts[2]
                    ins = int(ins_str) if ins_str.isdigit() else 0
                    dels = int(del_str) if del_str.isdigit() else 0
                    total_insertions += ins
                    total_deletions += dels
                    file_changes.append(
                        WorktreeFileChange(
                            file_path=path_str,
                            status="M",
                            insertions=ins,
                            deletions=dels,
                        )
                    )

        # Diff stat summary
        stat_res = self._run_git(
            ["diff", "--stat", f"{meta.base_commit}..HEAD"],
            cwd=wt_path,
        )
        diff_stat = stat_res.stdout.strip() if stat_res.returncode == 0 else ""

        return SubagentReviewSummary(
            subagent_id=meta.subagent_id,
            branch_name=meta.branch_name,
            worktree_path=wt_path,
            base_commit=meta.base_commit,
            head_commit=head_commit,
            commits_ahead=commits_ahead,
            commit_messages=commit_messages,
            is_dirty=is_dirty,
            changed_files=changed_files,
            file_changes=file_changes,
            total_insertions=total_insertions,
            total_deletions=total_deletions,
            diff_stat=diff_stat,
        )

    def precheck_merge(
        self,
        meta: SubagentWorktreeMeta,
        target_ref: str = "HEAD",
    ) -> MergePrecheckResult:
        """Performs dry-run pre-flight check to detect merge conflicts before applying."""
        repo = meta.repo_root
        target_res = self._run_git(["rev-parse", target_ref], cwd=repo)
        if target_res.returncode != 0:
            return MergePrecheckResult(
                can_merge=False,
                has_conflicts=False,
                conflicting_files=[],
                precheck_message=f"Invalid target ref '{target_ref}': {target_res.stderr.strip()}",
            )
        target_commit = target_res.stdout.strip()

        # Try git merge-tree --write-tree (available in git >= 2.38)
        merge_tree_res = self._run_git(
            ["merge-tree", "--write-tree", target_commit, meta.branch_name],
            cwd=repo,
        )
        if merge_tree_res.returncode == 0:
            return MergePrecheckResult(
                can_merge=True,
                has_conflicts=False,
                conflicting_files=[],
                precheck_message="Merge precheck clean: fast and conflict-free.",
            )

        # Conflict detected or merge-tree failed, parse conflict files
        conflicts: list[str] = []
        for line in merge_tree_res.stdout.splitlines():
            if "CONFLICT" in line:
                conflicts.append(line.strip())

        return MergePrecheckResult(
            can_merge=False,
            has_conflicts=True,
            conflicting_files=conflicts,
            precheck_message=f"Merge conflicts detected ({len(conflicts)} files contested).",
        )

    def execute_merge_and_cleanup(
        self,
        meta: SubagentWorktreeMeta,
        target_ref: str = "HEAD",
        strategy: MergeStrategy = MergeStrategy.SQUASH,
        commit_message: str | None = None,
        delete_branch_after: bool = True,
    ) -> WorktreeMergeResult:
        """Applies atomic merge of subagent worktree, removes worktree and cleans branch."""
        repo = meta.repo_root
        summary = self.inspect_worktree(meta)

        if summary.is_dirty:
            return WorktreeMergeResult(
                success=False,
                strategy=strategy,
                target_branch=target_ref,
                error_message="Subagent worktree contains uncommitted dirty changes; commit first.",
            )

        precheck = self.precheck_merge(meta, target_ref)
        if not precheck.can_merge and precheck.has_conflicts:
            return WorktreeMergeResult(
                success=False,
                strategy=strategy,
                target_branch=target_ref,
                conflicts=precheck.conflicting_files,
                error_message="Merge aborted due to detected conflicts in precheck gate.",
            )

        msg = commit_message or f"Merge subagent branch {meta.branch_name}"

        # Execute merge based on strategy
        if strategy == MergeStrategy.SQUASH:
            m_res = self._run_git(["merge", "--squash", meta.branch_name], cwd=repo)
            if m_res.returncode != 0:
                self._run_git(["merge", "--abort"], cwd=repo)
                return WorktreeMergeResult(
                    success=False,
                    strategy=strategy,
                    target_branch=target_ref,
                    error_message=f"Squash merge failed: {m_res.stderr.strip()}",
                )
            c_res = self._run_git(["commit", "-m", msg], cwd=repo)
            if c_res.returncode != 0:
                return WorktreeMergeResult(
                    success=False,
                    strategy=strategy,
                    target_branch=target_ref,
                    error_message=f"Commit after squash failed: {c_res.stderr.strip()}",
                )
        elif strategy == MergeStrategy.MERGE_COMMIT:
            m_res = self._run_git(["merge", "--no-ff", meta.branch_name, "-m", msg], cwd=repo)
            if m_res.returncode != 0:
                self._run_git(["merge", "--abort"], cwd=repo)
                return WorktreeMergeResult(
                    success=False,
                    strategy=strategy,
                    target_branch=target_ref,
                    error_message=f"Merge commit failed: {m_res.stderr.strip()}",
                )
        else:  # FAST_FORWARD_ONLY
            m_res = self._run_git(["merge", "--ff-only", meta.branch_name], cwd=repo)
            if m_res.returncode != 0:
                return WorktreeMergeResult(
                    success=False,
                    strategy=strategy,
                    target_branch=target_ref,
                    error_message=f"Fast-forward merge failed: {m_res.stderr.strip()}",
                )

        head_res = self._run_git(["rev-parse", "HEAD"], cwd=repo)
        merged_commit = head_res.stdout.strip() if head_res.returncode == 0 else ""

        # Remove worktree
        wt_pruned = False
        rm_res = self._run_git(["worktree", "remove", "--force", meta.worktree_path], cwd=repo)
        if rm_res.returncode == 0:
            wt_pruned = True

        # Delete temporary branch
        br_deleted = False
        if delete_branch_after:
            del_res = self._run_git(["branch", "-D", meta.branch_name], cwd=repo)
            if del_res.returncode == 0:
                br_deleted = True

        return WorktreeMergeResult(
            success=True,
            strategy=strategy,
            target_branch=target_ref,
            merged_commit=merged_commit,
            worktree_pruned=wt_pruned,
            branch_deleted=br_deleted,
        )

    def prune_if_clean(self, meta: SubagentWorktreeMeta) -> bool:
        """Automatically prunes worktree if there are 0 commits and no dirty modifications."""
        summary = self.inspect_worktree(meta)
        if summary.commits_ahead == 0 and not summary.is_dirty:
            repo = meta.repo_root
            self._run_git(["worktree", "remove", "--force", meta.worktree_path], cwd=repo)
            self._run_git(["branch", "-D", meta.branch_name], cwd=repo)
            return True
        return False

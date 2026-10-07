"""Core implementation of Git Worktree Multi-Branch Parallel Session Isolation Engine.

Provides deep session-to-worktree CWD binding, adaptive worktree context restoration,
project-root hierarchy aggregation, and safe removal guards protecting dirty files.

[INPUT]
- agent.context_management.worktree_isolation.worktree_isolation_types::SessionWorktreeBinding,
  WorktreeDescriptor, WorktreeHygieneReport, WorktreeHygieneStatus, WorktreeRemovalPolicy,
  WorktreeRemovalResult (POS: Type definitions for Git Worktree Multi-Branch Parallel Session Isolation and
  State Matrix.)

[OUTPUT]
- WorktreeSessionIsolationEngine: Manages multi-branch parallel worktree session bindings and safe lifecycle
  teardown.

[POS]
Core implementation of Git Worktree Multi-Branch Parallel Session Isolation Engine.
"""

from __future__ import annotations

import logging
import threading
from typing import Final

from .worktree_isolation_types import (
    SessionWorktreeBinding,
    WorktreeDescriptor,
    WorktreeHygieneReport,
    WorktreeHygieneStatus,
    WorktreeRemovalPolicy,
    WorktreeRemovalResult,
)

logger = logging.getLogger(__name__)


class WorktreeSessionIsolationEngine:
    """Manages multi-branch parallel worktree session bindings and safe lifecycle teardown."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._worktrees: dict[str, WorktreeDescriptor] = {}
        self._session_bindings: dict[str, SessionWorktreeBinding] = {}
        self._project_to_worktrees: dict[str, set[str]] = {}

    def register_worktree(self, descriptor: WorktreeDescriptor) -> None:
        """Register a worktree descriptor under its associated project root."""
        with self._lock:
            self._worktrees[descriptor.worktree_id] = descriptor
            if descriptor.project_root not in self._project_to_worktrees:
                self._project_to_worktrees[descriptor.project_root] = set()
            self._project_to_worktrees[descriptor.project_root].add(descriptor.worktree_id)

    def bind_session_to_worktree(
        self,
        session_id: str,
        worktree_id: str,
    ) -> SessionWorktreeBinding:
        """Deeply bind a session to a specific worktree directory for isolated execution."""
        with self._lock:
            if worktree_id not in self._worktrees:
                raise KeyError(f"Worktree '{worktree_id}' is not registered.")

            wt = self._worktrees[worktree_id]
            binding = SessionWorktreeBinding(
                session_id=session_id,
                worktree_id=worktree_id,
                bound_cwd=wt.worktree_path,
                branch_name=wt.branch_name,
            )
            self._session_bindings[session_id] = binding
            logger.info(
                "Session '%s' bound to worktree '%s' (%s) on branch '%s'",
                session_id,
                worktree_id,
                wt.worktree_path,
                wt.branch_name,
            )
            return binding

    def resolve_session_cwd(self, session_id: str) -> str:
        """Adaptively resolve the exact working directory locked to this session."""
        with self._lock:
            binding = self._session_bindings.get(session_id)
            if binding is None:
                raise KeyError(f"Session '{session_id}' has no worktree binding.")
            return binding.bound_cwd

    def get_session_binding(self, session_id: str) -> SessionWorktreeBinding | None:
        """Query active worktree binding for a session."""
        with self._lock:
            return self._session_bindings.get(session_id)

    def get_worktree(self, worktree_id: str) -> WorktreeDescriptor | None:
        """Lookup worktree descriptor by id."""
        with self._lock:
            return self._worktrees.get(worktree_id)

    def inspect_hygiene(
        self,
        worktree_id: str,
        uncommitted_files: tuple[str, ...] = (),
        untracked_files: tuple[str, ...] = (),
    ) -> WorktreeHygieneReport:
        """Inspect worktree cleanliness before permitting safe teardown."""
        with self._lock:
            if worktree_id not in self._worktrees:
                raise KeyError(f"Worktree '{worktree_id}' is not registered.")

            if uncommitted_files:
                status = WorktreeHygieneStatus.DIRTY_UNCOMMITTED
                safe = False
            elif untracked_files:
                status = WorktreeHygieneStatus.DIRTY_UNTRACKED
                safe = False
            else:
                status = WorktreeHygieneStatus.CLEAN
                safe = True

            return WorktreeHygieneReport(
                worktree_id=worktree_id,
                status=status,
                uncommitted_files=uncommitted_files,
                untracked_files=untracked_files,
                is_safe_to_remove=safe,
            )

    def safe_remove_worktree(
        self,
        worktree_id: str,
        hygiene_report: WorktreeHygieneReport,
        policy: WorktreeRemovalPolicy = WorktreeRemovalPolicy.SAFE_GUARD_BLOCK_IF_DIRTY,
    ) -> WorktreeRemovalResult:
        """Teardown a worktree with dirty file safe-guarding and force-purge override."""
        with self._lock:
            if worktree_id not in self._worktrees:
                raise KeyError(f"Worktree '{worktree_id}' is not registered.")

            wt = self._worktrees[worktree_id]
            if wt.is_main_checkout:
                return WorktreeRemovalResult(
                    worktree_id=worktree_id,
                    removed=False,
                    is_blocked_by_dirty=False,
                    uncommitted_count=len(hygiene_report.uncommitted_files),
                    untracked_count=len(hygiene_report.untracked_files),
                    policy_applied=policy,
                    message="Main checkout root cannot be removed.",
                )

            # Block if dirty and policy demands safe guard
            if not hygiene_report.is_safe_to_remove and policy == WorktreeRemovalPolicy.SAFE_GUARD_BLOCK_IF_DIRTY:
                logger.warning(
                    "Worktree removal blocked for '%s': uncommitted=%d, untracked=%d",
                    worktree_id,
                    len(hygiene_report.uncommitted_files),
                    len(hygiene_report.untracked_files),
                )
                return WorktreeRemovalResult(
                    worktree_id=worktree_id,
                    removed=False,
                    is_blocked_by_dirty=True,
                    uncommitted_count=len(hygiene_report.uncommitted_files),
                    untracked_count=len(hygiene_report.untracked_files),
                    policy_applied=policy,
                    message="Worktree contains uncommitted/untracked changes. Force purge required to override.",
                )

            # Safe to remove or force purge requested
            # Clean up all session bindings targeting this worktree
            sessions_to_unbind = [
                sid for sid, b in self._session_bindings.items() if b.worktree_id == worktree_id
            ]
            for sid in sessions_to_unbind:
                del self._session_bindings[sid]

            # Unregister from project mapping
            proj_set = self._project_to_worktrees.get(wt.project_root)
            if proj_set is not None:
                proj_set.discard(worktree_id)

            del self._worktrees[worktree_id]

            action_desc = "force purged" if not hygiene_report.is_safe_to_remove else "safely removed"
            return WorktreeRemovalResult(
                worktree_id=worktree_id,
                removed=True,
                is_blocked_by_dirty=False,
                uncommitted_count=len(hygiene_report.uncommitted_files),
                untracked_count=len(hygiene_report.untracked_files),
                policy_applied=policy,
                message=f"Worktree '{worktree_id}' successfully {action_desc}.",
            )

    def get_project_worktrees(self, project_root: str) -> tuple[WorktreeDescriptor, ...]:
        """List all registered worktrees associated with a project root."""
        with self._lock:
            wt_ids = self._project_to_worktrees.get(project_root, set())
            return tuple(self._worktrees[wid] for wid in wt_ids if wid in self._worktrees)

    def get_project_tree_matrix(
        self,
        project_root: str,
    ) -> dict[str, tuple[WorktreeDescriptor, tuple[str, ...]]]:
        """Aggregate project worktrees and their deeply bound sessions for sidebar matrix."""
        with self._lock:
            result: dict[str, tuple[WorktreeDescriptor, tuple[str, ...]]] = {}
            wt_ids = self._project_to_worktrees.get(project_root, set())

            for wid in wt_ids:
                if wid not in self._worktrees:
                    continue
                wt = self._worktrees[wid]
                bound_sessions = tuple(
                    sid for sid, b in self._session_bindings.items() if b.worktree_id == wid
                )
                result[wid] = (wt, bound_sessions)

            return result

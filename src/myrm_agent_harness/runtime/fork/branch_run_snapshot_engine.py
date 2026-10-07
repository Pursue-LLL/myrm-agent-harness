"""Manages immutable run-level forks, policy snapshot inheritance, and artifact diffs.

[INPUT]
- runtime.fork.branch_run_types::ArtifactDiffItem, BranchArtifactComparison, BranchRun, IntentSnapshot,
  PolicySnapshot, RunAttempt, RunStatus (POS: Types and models for branch run.)

[OUTPUT]
- BranchRunSnapshotEngine: Manages immutable run-level forks, policy snapshot inheritance, and artifact diffs.

[POS]
Manages immutable run-level forks, policy snapshot inheritance, and artifact diffs.
"""

# ============================================================================
# BranchRunSnapshotEngine (Item 152)
# Production-grade dual-branching Run snapshot engine: immutable policy inheritance,
# durable attempt ledger preservation, cross-branch artifact diffs & linear projection.
# ============================================================================

from __future__ import annotations

import logging
import time
import uuid

from .branch_run_types import (
    ArtifactDiffItem,
    BranchArtifactComparison,
    BranchRun,
    IntentSnapshot,
    PolicySnapshot,
    RunAttempt,
    RunStatus,
)

logger = logging.getLogger(__name__)


class BranchRunSnapshotEngine:
    """Manages immutable run-level forks, policy snapshot inheritance, and artifact diffs."""

    def __init__(self) -> None:
        self._runs_by_id: dict[str, BranchRun] = {}
        self._runs_by_session: dict[str, list[str]] = {}
        self._active_run_by_session: dict[str, str] = {}

    def create_initial_run(
        self,
        session_id: str,
        policy: PolicySnapshot,
        intent: IntentSnapshot,
        custom_run_id: str | None = None,
    ) -> BranchRun:
        """Initializes the root BranchRun for a new session."""
        run_id = custom_run_id or f"run-{uuid.uuid4().hex[:12]}"
        run = BranchRun(
            run_id=run_id,
            session_id=session_id,
            parent_run_id=None,
            fork_node_id=None,
            policy_snapshot=policy,
            intent_snapshot=intent,
            status=RunStatus.RUNNING,
            created_at=time.time(),
        )
        self._runs_by_id[run_id] = run
        self._runs_by_session.setdefault(session_id, []).append(run_id)
        self._active_run_by_session[session_id] = run_id
        return run

    def record_attempt(
        self,
        run_id: str,
        tool_call_count: int,
        duration_ms: float,
        status: RunStatus,
        error_message: str = "",
        thought_trace: str = "",
    ) -> RunAttempt:
        """Appends an immutable execution attempt to a run's audit history."""
        run = self._runs_by_id.get(run_id)
        if not run:
            raise KeyError(f"Run ID not found: {run_id}")

        attempt_num = len(run.attempt_history) + 1
        attempt = RunAttempt(
            attempt_id=f"att-{uuid.uuid4().hex[:8]}",
            attempt_number=attempt_num,
            tool_call_count=tool_call_count,
            duration_ms=duration_ms,
            status=status,
            error_message=error_message,
            thought_trace=thought_trace,
            timestamp=time.time(),
        )
        run.attempt_history.append(attempt)
        return attempt

    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        generated_artifact_ids: list[str] | None = None,
    ) -> BranchRun:
        """Marks run as finished with final status and produced artifact IDs."""
        run = self._runs_by_id.get(run_id)
        if not run:
            raise KeyError(f"Run ID not found: {run_id}")

        run.status = status
        run.finished_at = time.time()
        if generated_artifact_ids:
            run.generated_artifact_ids = list(generated_artifact_ids)
        return run

    def fork_branch_run(
        self,
        parent_run_id: str,
        fork_node_id: str,
        new_intent: IntentSnapshot,
        override_policy: PolicySnapshot | None = None,
        custom_run_id: str | None = None,
    ) -> BranchRun:
        """Forks a new BranchRun snapshot without mutating or truncating parent history."""
        parent_run = self._runs_by_id.get(parent_run_id)
        if not parent_run:
            raise KeyError(f"Parent Run ID not found: {parent_run_id}")

        # Deeply inherit parent policy snapshot unless explicitly overridden
        effective_policy = override_policy or parent_run.policy_snapshot
        new_run_id = custom_run_id or f"run-{uuid.uuid4().hex[:12]}"

        branch_run = BranchRun(
            run_id=new_run_id,
            session_id=parent_run.session_id,
            parent_run_id=parent_run.run_id,
            fork_node_id=fork_node_id,
            policy_snapshot=effective_policy,
            intent_snapshot=new_intent,
            status=RunStatus.PENDING,
            created_at=time.time(),
        )

        self._runs_by_id[new_run_id] = branch_run
        self._runs_by_session.setdefault(parent_run.session_id, []).append(new_run_id)
        self._active_run_by_session[parent_run.session_id] = new_run_id

        logger.info(
            "Forked new BranchRun %s from parent %s at fork_node %s",
            new_run_id,
            parent_run_id,
            fork_node_id,
        )
        return branch_run

    def switch_active_branch(self, session_id: str, target_run_id: str) -> list[BranchRun]:
        """Switches active branch pointer and returns linear lineage from root to target."""
        target_run = self._runs_by_id.get(target_run_id)
        if not target_run or target_run.session_id != session_id:
            raise ValueError(f"Run {target_run_id} does not belong to session {session_id}")

        self._active_run_by_session[session_id] = target_run_id

        # Reconstruct linear execution lineage backwards
        lineage: list[BranchRun] = []
        curr: BranchRun | None = target_run
        visited: set[str] = set()

        while curr:
            if curr.run_id in visited:
                break  # Cycle defense
            visited.add(curr.run_id)
            lineage.append(curr)
            curr = self._runs_by_id.get(curr.parent_run_id) if curr.parent_run_id else None

        lineage.reverse()
        return lineage

    def compare_branch_artifacts(
        self,
        source_run_id: str,
        target_run_id: str,
        artifact_contents: dict[str, str] | None = None,
    ) -> BranchArtifactComparison:
        """Inspects and compares artifacts produced across two distinct branch runs."""
        source_run = self._runs_by_id.get(source_run_id)
        target_run = self._runs_by_id.get(target_run_id)
        if not source_run or not target_run:
            raise KeyError(f"Invalid run pair: {source_run_id}, {target_run_id}")

        source_set = set(source_run.generated_artifact_ids)
        target_set = set(target_run.generated_artifact_ids)
        common = sorted(source_set.intersection(target_set))

        divergent: list[ArtifactDiffItem] = []

        # Artifacts present in source but removed in target
        for art_id in sorted(source_set - target_set):
            divergent.append(
                ArtifactDiffItem(
                    artifact_id=art_id,
                    change_type="REMOVED",
                    diff_details=f"Present in {source_run_id}, missing in {target_run_id}",
                )
            )

        # Artifacts added in target
        for art_id in sorted(target_set - source_set):
            divergent.append(
                ArtifactDiffItem(
                    artifact_id=art_id,
                    change_type="ADDED",
                    diff_details=f"New artifact produced in {target_run_id}",
                )
            )

        # Content diff check for common artifacts if contents mapping is supplied
        if artifact_contents:
            for art_id in common:
                # E.g. keyed as f"{run_id}:{art_id}"
                c_src = artifact_contents.get(f"{source_run_id}:{art_id}")
                c_tgt = artifact_contents.get(f"{target_run_id}:{art_id}")
                if c_src is not None and c_tgt is not None and c_src != c_tgt:
                    divergent.append(
                        ArtifactDiffItem(
                            artifact_id=art_id,
                            change_type="MODIFIED",
                            diff_details=f"Content modified between {source_run_id} and {target_run_id}",
                        )
                    )

        summary = (
            f"Comparison between {source_run_id} and {target_run_id}: "
            f"{len(common)} common artifact(s), {len(divergent)} mutation(s)."
        )

        return BranchArtifactComparison(
            source_run_id=source_run_id,
            target_run_id=target_run_id,
            common_artifact_count=len(common),
            divergent_artifacts=divergent,
            summary=summary,
        )

    def get_run(self, run_id: str) -> BranchRun | None:
        """Retrieves a BranchRun by ID."""
        return self._runs_by_id.get(run_id)

    def get_active_run(self, session_id: str) -> BranchRun | None:
        """Retrieves the currently active BranchRun for a given session."""
        active_id = self._active_run_by_session.get(session_id)
        return self._runs_by_id.get(active_id) if active_id else None

    def list_branch_runs(self, session_id: str) -> list[BranchRun]:
        """Lists all branch runs associated with a session in order of creation."""
        run_ids = self._runs_by_session.get(session_id, [])
        return [self._runs_by_id[r] for r in run_ids if r in self._runs_by_id]

"""Conflict detector evaluating parallel workers write-sets before merge.

[INPUT]
- types.WriteFingerprint, types.WorkConflictItem, types.ConflictGateVerdict
- types.ResolutionStrategy

[OUTPUT]
- ParallelWorkConflictDetector

[POS]
myrm_agent_harness/agent/sub_agents/conflict_gate/detector.py
"""

from __future__ import annotations

import collections
import logging
import threading
from datetime import UTC, datetime

from myrm_agent_harness.agent.sub_agents.conflict_gate.types import (
    ConflictGateVerdict,
    ResolutionStrategy,
    WorkConflictItem,
    WriteFingerprint,
)

logger = logging.getLogger(__name__)


class ParallelWorkConflictDetector:
    """Thread-safe detector identifying concurrent file/artifact mutation conflicts."""

    def __init__(self) -> None:
        self._conflicts: dict[str, WorkConflictItem] = {}
        self._lock: threading.Lock = threading.Lock()
        self._counter: int = 0

    def evaluate_write_fingerprints(
        self, session_id: str, fingerprints: list[WriteFingerprint]
    ) -> ConflictGateVerdict:
        """Evaluate a batch of worker write fingerprints and detect concurrent collisions."""
        grouped: dict[tuple[str, str], list[WriteFingerprint]] = collections.defaultdict(list)
        for fp in fingerprints:
            key = (fp.resource_id, fp.mutation_type)
            grouped[key].append(fp)

        detected_conflicts: list[WorkConflictItem] = []
        clean_writes: list[WriteFingerprint] = []

        with self._lock:
            for (res_id, mut_type), writes in grouped.items():
                if len(writes) <= 1:
                    clean_writes.extend(writes)
                    continue

                # Check if multiple distinct workers mutated this resource
                distinct_workers = {w.worker_id for w in writes}
                if len(distinct_workers) <= 1:
                    clean_writes.extend(writes)
                    continue

                # Check hash divergence
                distinct_hashes = {w.content_hash for w in writes}
                if len(distinct_hashes) <= 1:
                    # Identical content written by multiple workers is idempotent/safe
                    clean_writes.extend(writes)
                    continue

                # Collision detected between workers
                self._counter += 1
                conflict_id = f"conf-{session_id}-{self._counter}"
                worker_a = writes[0]
                worker_b = writes[1]

                item = WorkConflictItem(
                    conflict_id=conflict_id,
                    session_id=session_id,
                    resource_id=res_id,
                    mutation_type=mut_type,
                    worker_a=worker_a,
                    worker_b=worker_b,
                    status="conflict_pending",
                )
                self._conflicts[conflict_id] = item
                detected_conflicts.append(item)

        is_blocked = len(detected_conflicts) > 0
        return ConflictGateVerdict(
            is_blocked=is_blocked,
            total_conflicts=len(detected_conflicts),
            conflicts=detected_conflicts,
            clean_writes=clean_writes,
        )

    def resolve_conflict(
        self,
        conflict_id: str,
        strategy: ResolutionStrategy,
        resolved_content: str | None = None,
    ) -> WorkConflictItem | None:
        """Apply a resolution strategy to reconcile a pending conflict."""
        with self._lock:
            conflict = self._conflicts.get(conflict_id)
            if not conflict:
                return None

            conflict.status = "resolved"
            conflict.resolution_strategy = strategy
            conflict.resolved_content = resolved_content
            conflict.resolved_at = datetime.now(UTC).isoformat()
            return conflict

    def get_pending_conflicts(self, session_id: str) -> list[WorkConflictItem]:
        """Fetch all unresolved conflicts for a specific session."""
        with self._lock:
            return [
                c
                for c in self._conflicts.values()
                if c.session_id == session_id and c.status == "conflict_pending"
            ]

    def get_conflict_by_id(self, conflict_id: str) -> WorkConflictItem | None:
        """Fetch a conflict item by ID."""
        with self._lock:
            return self._conflicts.get(conflict_id)

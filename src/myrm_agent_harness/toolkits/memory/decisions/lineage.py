"""[POS]: src/myrm_agent_harness/toolkits/memory/decisions/lineage.py
[INPUT]: DecisionRecord entities and lineage transition intents.
[OUTPUT]: Cycle-validated DAG lineage evolution chains and status mutations.
"""

from collections.abc import Callable

from .models import DecisionRecord, DecisionStatus


class LineageCycleError(ValueError):
    """Raised when an active-to-superseded transition would form a cyclic lineage loop."""


class DecisionLineageEngine:
    """State machine governing decision lifecycle and acyclic lineage trees."""

    @classmethod
    def validate_transition(
        cls,
        new_id: str,
        supersedes_id: str | None,
        get_record_fn: Callable[[str], DecisionRecord | None],
    ) -> None:
        """Verify that superseding a parent decision does not form a recursive loop."""
        if not supersedes_id:
            return

        if new_id == supersedes_id:
            raise LineageCycleError(f"Decision '{new_id}' cannot supersede itself.")

        visited: set[str] = {new_id}
        current_id: str | None = supersedes_id

        # Traverse ancestry backwards to verify no loop reaches new_id
        while current_id:
            if current_id in visited:
                raise LineageCycleError(
                    f"Lineage cycle detected: '{new_id}' -> '{supersedes_id}' "
                    f"forms a closed loop through '{current_id}'."
                )
            visited.add(current_id)
            parent = get_record_fn(current_id)
            if not parent:
                break
            current_id = parent.supersedes_id

    @classmethod
    def apply_supersession(
        cls,
        old_record: DecisionRecord,
        new_record: DecisionRecord,
        iso_timestamp: str,
    ) -> DecisionRecord:
        """Transition the old record to SUPERSEDED pointing to the new record."""
        updated_old = old_record.model_copy(
            update={
                "status": DecisionStatus.SUPERSEDED,
                "superseded_by": new_record.id,
                "updated_at": iso_timestamp,
            }
        )
        return updated_old

    @classmethod
    def trace_ancestry(
        cls,
        head_id: str,
        get_record_fn: Callable[[str], DecisionRecord | None],
        max_depth: int = 50,
    ) -> list[DecisionRecord]:
        """Return full chronological lineage chain from root ancestor to current record."""
        chain: list[DecisionRecord] = []
        visited: set[str] = set()
        curr_id: str | None = head_id

        while curr_id and len(chain) < max_depth:
            if curr_id in visited:
                break
            visited.add(curr_id)
            rec = get_record_fn(curr_id)
            if not rec:
                break
            chain.append(rec)
            curr_id = rec.supersedes_id

        # Reverse so root is first, latest is last
        chain.reverse()
        return chain

    @classmethod
    def find_active_successor(
        cls,
        start_id: str,
        get_record_fn: Callable[[str], DecisionRecord | None],
        max_depth: int = 50,
    ) -> DecisionRecord | None:
        """Follow superseded_by pointers forward to locate the current active successor."""
        curr_id: str | None = start_id
        visited: set[str] = set()

        while curr_id and len(visited) < max_depth:
            if curr_id in visited:
                return None
            visited.add(curr_id)
            rec = get_record_fn(curr_id)
            if not rec:
                return None
            if rec.status == DecisionStatus.ACTIVE:
                return rec
            curr_id = rec.superseded_by

        return None

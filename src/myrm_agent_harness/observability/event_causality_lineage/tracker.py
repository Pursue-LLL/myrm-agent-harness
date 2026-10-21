"""[INPUT] Causality lineage events (external trigger, rule, agent actions, artifact changes).
[OUTPUT] Thread-safe registry enabling DAG lineage queries and 1-second reverse file change attribution.
[POS] myrm_agent_harness.observability.event_causality_lineage.tracker

Thread-safe causality lineage tracker:
1. Records complete event-to-action DAG chains.
2. Maintains inverted index for instant reverse file change attribution.
3. Provides white-box accountability for event-driven autonomous agents.
"""

from collections import defaultdict
import threading
import time

from .models import (
    AgentActionNode,
    ArtifactChangeRecord,
    CausalityLineageRecord,
    CausalityRuleMatch,
    ExternalEventTrigger,
    FileAttributionResult,
)


class EventCausalityTracker:
    """Thread-safe causality registry mapping external triggers to internal agent actions and file diffs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # causality_trace_id -> CausalityLineageRecord
        self._lineages: dict[str, CausalityLineageRecord] = {}
        # file_path -> list of FileAttributionResult
        self._file_index: dict[str, list[FileAttributionResult]] = defaultdict(list)

    def record_lineage(
        self,
        causality_trace_id: str,
        session_id: str,
        trigger: ExternalEventTrigger,
        rule: CausalityRuleMatch,
        agent_role: str,
        actions: tuple[AgentActionNode, ...] | list[AgentActionNode],
        artifacts: tuple[ArtifactChangeRecord, ...] | list[ArtifactChangeRecord],
    ) -> CausalityLineageRecord:
        """Register an end-to-end event-driven causality lineage record and update the reverse index."""
        clean_cid = causality_trace_id.strip()
        clean_sid = session_id.strip()

        tot_tokens = sum(a.tokens_consumed for a in actions)
        tot_duration = sum(a.duration_ms for a in actions)

        record = CausalityLineageRecord(
            causality_trace_id=clean_cid,
            session_id=clean_sid,
            trigger=trigger,
            rule=rule,
            agent_role=agent_role.strip(),
            actions=tuple(actions),
            artifacts=tuple(artifacts),
            total_tokens=tot_tokens,
            total_duration_ms=tot_duration,
            created_at_ms=int(time.time() * 1000),
        )

        with self._lock:
            self._lineages[clean_cid] = record

            # Update inverted index for every touched artifact
            for art in artifacts:
                # Primary rationale from last action or generic description
                rat = actions[-1].decision_rationale if actions else f"Automated modification by {agent_role}"
                attr = FileAttributionResult(
                    file_path=art.file_path,
                    causality_trace_id=clean_cid,
                    trigger_event_id=trigger.event_id,
                    source_type=trigger.source_type,
                    event_name=trigger.event_name,
                    agent_role=agent_role.strip(),
                    change_record=art,
                    rationale=rat,
                    occurred_at_ms=art.timestamp_ms,
                )
                self._file_index[art.file_path].append(attr)

        return record

    def get_lineage(self, causality_trace_id: str) -> CausalityLineageRecord | None:
        """Retrieve complete causality DAG by trace ID."""
        with self._lock:
            return self._lineages.get(causality_trace_id.strip())

    def list_lineages(
        self,
        source_type: str | None = None,
        event_id: str | None = None,
        limit: int = 50,
    ) -> list[CausalityLineageRecord]:
        """Query lineages with optional filtering."""
        with self._lock:
            results = list(self._lineages.values())

        if source_type:
            st = source_type.strip().lower()
            results = [r for r in results if r.trigger.source_type.lower() == st]

        if event_id:
            eid = event_id.strip()
            results = [r for r in results if r.trigger.event_id == eid]

        results.sort(key=lambda r: r.created_at_ms, reverse=True)
        return results[: max(1, limit)]

    def reverse_lookup_file(self, file_path: str) -> list[FileAttributionResult]:
        """Reverse trace all external events and rationale that modified a specific file."""
        clean_path = file_path.strip()
        with self._lock:
            matches = list(self._file_index.get(clean_path, []))
            matches.sort(key=lambda m: m.occurred_at_ms, reverse=True)
            return matches

    def reset(self) -> None:
        """Clear all registered lineages and reverse indexes."""
        with self._lock:
            self._lineages.clear()
            self._file_index.clear()


# Global thread-safe singleton
_default_tracker: EventCausalityTracker | None = None
_tracker_lock = threading.Lock()


def get_default_event_causality_tracker() -> EventCausalityTracker:
    """Retrieve or initialize the global EventCausalityTracker instance."""
    global _default_tracker
    if _default_tracker is None:
        with _tracker_lock:
            if _default_tracker is None:
                _default_tracker = EventCausalityTracker()
    return _default_tracker

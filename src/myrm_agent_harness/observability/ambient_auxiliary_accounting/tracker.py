"""[INPUT] Invocations captured inside ambient auxiliary contexts.
[OUTPUT] Thread-safe in-memory tracker aggregating auxiliary vs core task footprints and reporting breakdown metrics.
[POS] myrm_agent_harness.observability.ambient_auxiliary_accounting.tracker

Thread-safe tracker aggregating LLM/tool invocations partitioned by task dimensions:
Maintains prompt cache purity by isolating background derivative jobs from core chat history.
"""

from collections import defaultdict
import threading
import time

from .context import get_current_ambient_task
from .models import (
    AmbientAccountingReport,
    AuxiliaryTaskType,
    AuxiliaryUsageSnapshot,
    TaskCostSummary,
)


class AmbientAuxiliaryAccountingTracker:
    """Thread-safe tracker aggregating usage partitioned by ambient task dimensions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # session_id -> list of AuxiliaryUsageSnapshot
        self._snapshots: dict[str, list[AuxiliaryUsageSnapshot]] = defaultdict(list)

    def record_invocation(
        self,
        session_id: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float = 0.0,
        cost_usd: float = 0.0,
        task_type: AuxiliaryTaskType | str | None = None,
        custom_task_name: str = "",
        model: str = "",
        timestamp_ms: int | None = None,
    ) -> AuxiliaryUsageSnapshot:
        """Record an LLM or tool call, automatically sniffing ambient task context if unspecified."""
        ambient_task, ambient_custom, ambient_model = get_current_ambient_task()

        resolved_task: AuxiliaryTaskType
        if task_type is not None:
            if isinstance(task_type, AuxiliaryTaskType):
                resolved_task = task_type
            else:
                try:
                    resolved_task = AuxiliaryTaskType(task_type.strip().lower())
                except ValueError:
                    resolved_task = AuxiliaryTaskType.CUSTOM
        else:
            resolved_task = ambient_task

        resolved_custom = custom_task_name.strip() or ambient_custom
        resolved_model = model.strip() or ambient_model or "default_model"
        clean_sid = session_id.strip() or "global"
        now_ms = timestamp_ms or int(time.time() * 1000)

        snapshot = AuxiliaryUsageSnapshot(
            session_id=clean_sid,
            task_type=resolved_task,
            custom_task_name=resolved_custom,
            model=resolved_model,
            input_tokens=max(0, input_tokens),
            output_tokens=max(0, output_tokens),
            duration_ms=max(0.0, duration_ms),
            cost_usd=max(0.0, cost_usd),
            timestamp_ms=now_ms,
        )

        with self._lock:
            self._snapshots[clean_sid].append(snapshot)

        return snapshot

    def get_recent_snapshots(
        self,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[AuxiliaryUsageSnapshot]:
        """Retrieve recent snapshots matching session filter."""
        with self._lock:
            if session_id:
                active = list(self._snapshots.get(session_id.strip(), []))
            else:
                active = [s for sublist in self._snapshots.values() for s in sublist]

            active.sort(key=lambda s: s.timestamp_ms, reverse=True)
            return active[: max(1, limit)]

    def get_accounting_report(self, session_id: str | None = None) -> AmbientAccountingReport:
        """Aggregate breakdown metrics comparing core dialogue vs auxiliary operations."""
        with self._lock:
            if session_id:
                active = list(self._snapshots.get(session_id.strip(), []))
            else:
                active = [s for sublist in self._snapshots.values() for s in sublist]

        total_invocations = len(active)
        total_cost = sum(s.cost_usd for s in active)
        core_cost = sum(s.cost_usd for s in active if s.task_type == AuxiliaryTaskType.MAIN_DIALOGUE)
        aux_cost = sum(s.cost_usd for s in active if s.task_type != AuxiliaryTaskType.MAIN_DIALOGUE)
        aux_share_pct = round((aux_cost / total_cost) * 100.0, 1) if total_cost > 0.0 else 0.0

        # Group by effective task name
        grouped: dict[str, list[AuxiliaryUsageSnapshot]] = defaultdict(list)
        for s in active:
            grouped[s.effective_task_name].append(s)

        summaries: list[TaskCostSummary] = []
        for tname, items in grouped.items():
            cnt = len(items)
            tin = sum(i.input_tokens for i in items)
            tout = sum(i.output_tokens for i in items)
            tcost = sum(i.cost_usd for i in items)
            avg_dur = sum(i.duration_ms for i in items) / cnt if cnt > 0 else 0.0
            share = round((tcost / total_cost) * 100.0, 1) if total_cost > 0.0 else 0.0

            summaries.append(
                TaskCostSummary(
                    task_name=tname,
                    call_count=cnt,
                    total_input_tokens=tin,
                    total_output_tokens=tout,
                    total_tokens=tin + tout,
                    total_cost_usd=round(tcost, 6),
                    avg_duration_ms=round(avg_dur, 1),
                    share_pct=share,
                )
            )

        summaries.sort(key=lambda x: x.total_cost_usd, reverse=True)

        return AmbientAccountingReport(
            total_invocations=total_invocations,
            total_cost_usd=round(total_cost, 6),
            core_dialogue_cost_usd=round(core_cost, 6),
            auxiliary_cost_usd=round(aux_cost, 6),
            auxiliary_cost_share_pct=aux_share_pct,
            task_summaries=tuple(summaries),
            prompt_cache_purity_preserved=True,
        )

    def reset(self, session_id: str | None = None) -> None:
        """Clear usage telemetry for a specific session or entirely."""
        with self._lock:
            if session_id:
                self._snapshots.pop(session_id.strip(), None)
            else:
                self._snapshots.clear()


# Global thread-safe singleton
_default_tracker: AmbientAuxiliaryAccountingTracker | None = None
_tracker_lock = threading.Lock()


def get_default_auxiliary_tracker() -> AmbientAuxiliaryAccountingTracker:
    """Retrieve or initialize the global AmbientAuxiliaryAccountingTracker instance."""
    global _default_tracker
    if _default_tracker is None:
        with _tracker_lock:
            if _default_tracker is None:
                _default_tracker = AmbientAuxiliaryAccountingTracker()
    return _default_tracker

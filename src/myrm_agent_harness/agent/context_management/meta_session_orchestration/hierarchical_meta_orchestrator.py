# [INPUT]: MetaSessionConfig, SubSessionFailureReport, SubSessionHandoffDigest, SubSessionProgressCard, SubSessionStatus, SubSessionTaskDescriptor, compute_digest_hash from orchestration_types, SubSessionFaultIsolator from sub_session_fault_isolator
# [OUTPUT]: HierarchicalMetaSessionOrchestrator, format_meta_progress_hud
# [POS]: myrm_agent_harness.agent.context_management.meta_session_orchestration.hierarchical_meta_orchestrator
"""Hierarchical Meta-Session & Sub-Session Cascading Orchestrator (Item 332).

Dispatches, coordinates, tracks, and aggregates multiple worker sub-sessions from
a single parent conversation entry point, providing realtime HUD progress streaming.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Final

from myrm_agent_harness.agent.context_management.meta_session_orchestration.orchestration_types import (
    MetaSessionConfig,
    SubSessionFailureReport,
    SubSessionHandoffDigest,
    SubSessionProgressCard,
    SubSessionStatus,
    SubSessionTaskDescriptor,
    compute_digest_hash,
)
from myrm_agent_harness.agent.context_management.meta_session_orchestration.sub_session_fault_isolator import (
    SubSessionFaultIsolator,
)


def format_meta_progress_hud(cards: list[SubSessionProgressCard]) -> str:
    """Format active sub-session progress cards into a realtime HUD summary markdown block."""
    if not cards:
        return ""

    lines: list[str] = [
        "=== META-SESSION MULTI-TASK PROGRESS HUD ===",
        "Live status of worker sub-sessions dispatched from this conversation:",
    ]
    for idx, card in enumerate(cards, 1):
        status_tag = card.status.value.upper()
        lines.append(
            f"[{idx}] {card.title} (ID: {card.task_id}) | Status: [{status_tag}] | Step: '{card.current_step}'"
        )
        substeps_str = ", ".join(card.completed_substeps) if card.completed_substeps else "None"
        lines.append(
            f"    Duration: {card.elapsed_seconds:.1f}s | Tokens: {card.tokens_consumed} | Milestones: {substeps_str}"
        )
        if card.active_tool:
            lines.append(f"    Active Tool: '{card.active_tool}'")
    lines.append("=============================================")
    return "\n".join(lines)


class HierarchicalMetaSessionOrchestrator:
    """Cascade orchestrator managing worker sub-session lifecycles and parent HUD aggregations."""

    def __init__(
        self,
        config: MetaSessionConfig | None = None,
        fault_isolator: SubSessionFaultIsolator | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._config: Final[MetaSessionConfig] = config or MetaSessionConfig()
        self._fault_isolator: Final[SubSessionFaultIsolator] = (
            fault_isolator or SubSessionFaultIsolator()
        )
        # (meta_session_id, task_id) -> SubSessionProgressCard
        self._cards: dict[tuple[str, str], SubSessionProgressCard] = {}
        # (meta_session_id, task_id) -> start_timestamp_monotonic
        self._start_times: dict[tuple[str, str], float] = {}

    @property
    def config(self) -> MetaSessionConfig:
        """Active orchestrator configuration."""
        return self._config

    @property
    def fault_isolator(self) -> SubSessionFaultIsolator:
        """Underlying sub-session fault containment engine."""
        return self._fault_isolator

    def dispatch_sub_session(
        self,
        descriptor: SubSessionTaskDescriptor,
    ) -> SubSessionProgressCard:
        """Dispatch a new worker sub-session from the parent meta-session.

        Args:
            descriptor: Full specification of the sub-task.

        Returns:
            Initial SubSessionProgressCard with RUNNING status.

        Raises:
            RuntimeError: If maximum concurrent active sub-sessions limit is exceeded.
        """
        with self._lock:
            # Check concurrent running limit
            active_count = sum(
                1
                for (m_id, _), card in self._cards.items()
                if m_id == descriptor.meta_session_id
                and card.status in (SubSessionStatus.PENDING, SubSessionStatus.RUNNING)
            )
            if active_count >= self._config.max_concurrent_sub_sessions:
                raise RuntimeError(
                    f"Meta-session '{descriptor.meta_session_id}' reached max concurrent "
                    f"sub-sessions limit ({self._config.max_concurrent_sub_sessions})."
                )

            key = (descriptor.meta_session_id, descriptor.task_id)
            self._start_times[key] = time.monotonic()

            card = SubSessionProgressCard(
                task_id=descriptor.task_id,
                meta_session_id=descriptor.meta_session_id,
                title=descriptor.title,
                status=SubSessionStatus.RUNNING,
                current_step="Dispatched and initializing worker sandbox",
                elapsed_seconds=0.0,
                tokens_consumed=0,
                completed_substeps=[],
                active_tool="",
                updated_at_iso=datetime.now(timezone.utc).isoformat(),
            )
            self._cards[key] = card
            return card

    def update_sub_session_progress(
        self,
        meta_session_id: str,
        task_id: str,
        current_step: str,
        active_tool: str = "",
        tokens_consumed: int = 0,
        add_completed_substep: str = "",
    ) -> SubSessionProgressCard:
        """Update live execution milestones for an active sub-session.

        Args:
            meta_session_id: Parent meta-session identifier.
            task_id: Worker sub-session identifier.
            current_step: Description of current operation.
            active_tool: Tool currently running.
            tokens_consumed: Cumulative tokens used by sub-session.
            add_completed_substep: Optional milestone to append to completed list.

        Returns:
            Updated SubSessionProgressCard.
        """
        with self._lock:
            key = (meta_session_id, task_id)
            card = self._cards.get(key)
            if not card:
                raise KeyError(
                    f"No active progress card found for task '{task_id}' in meta '{meta_session_id}'"
                )

            start_t = self._start_times.get(key, time.monotonic())
            elapsed = time.monotonic() - start_t

            completed = list(card.completed_substeps)
            if add_completed_substep and add_completed_substep not in completed:
                completed.append(add_completed_substep)

            updated_card = card.model_copy(
                update={
                    "current_step": current_step,
                    "active_tool": active_tool,
                    "tokens_consumed": tokens_consumed or card.tokens_consumed,
                    "elapsed_seconds": round(elapsed, 2),
                    "completed_substeps": completed,
                    "updated_at_iso": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._cards[key] = updated_card
            return updated_card

    def complete_sub_session(
        self,
        meta_session_id: str,
        task_id: str,
        outcome_summary: str,
        deliverables: list[str] | None = None,
        lessons_learned: list[str] | None = None,
    ) -> tuple[SubSessionProgressCard, SubSessionHandoffDigest]:
        """Mark sub-session as successfully completed and generate handoff brief.

        Args:
            meta_session_id: Parent meta-session identifier.
            task_id: Completed sub-session task identifier.
            outcome_summary: Concise narrative of final accomplishments.
            deliverables: List of generated artifacts or files.
            lessons_learned: Key lessons or tips preserved.

        Returns:
            tuple of (final SubSessionProgressCard, SubSessionHandoffDigest)
        """
        deliv = deliverables or []
        lessons = lessons_learned or []

        with self._lock:
            key = (meta_session_id, task_id)
            card = self._cards.get(key)
            if not card:
                raise KeyError(
                    f"No active progress card found for task '{task_id}' in meta '{meta_session_id}'"
                )

            start_t = self._start_times.get(key, time.monotonic())
            elapsed = time.monotonic() - start_t

            final_card = card.model_copy(
                update={
                    "status": SubSessionStatus.COMPLETED,
                    "current_step": "Task completed successfully",
                    "active_tool": "",
                    "elapsed_seconds": round(elapsed, 2),
                    "updated_at_iso": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._cards[key] = final_card

            digest_hash = compute_digest_hash(
                task_id=task_id,
                meta_session_id=meta_session_id,
                outcome_summary=outcome_summary,
                deliverables=deliv,
            )

            digest = SubSessionHandoffDigest(
                task_id=task_id,
                meta_session_id=meta_session_id,
                title=card.title,
                outcome_summary=outcome_summary,
                deliverables=deliv,
                lessons_learned=lessons,
                digest_hash=digest_hash,
            )
            return final_card, digest

    def fail_sub_session(
        self,
        meta_session_id: str,
        task_id: str,
        exc: Exception,
    ) -> tuple[SubSessionProgressCard, SubSessionFailureReport]:
        """Isolate worker sub-session exception, update card to FAILED, and return report.

        Args:
            meta_session_id: Parent meta-session identifier.
            task_id: Worker task identifier.
            exc: Exception raised within sub-session.

        Returns:
            tuple of (final SubSessionProgressCard, SubSessionFailureReport)
        """
        report = self._fault_isolator.isolate_failure(
            task_id=task_id,
            meta_session_id=meta_session_id,
            exc=exc,
        )

        with self._lock:
            key = (meta_session_id, task_id)
            card = self._cards.get(key)
            title = card.title if card else task_id
            start_t = self._start_times.get(key, time.monotonic())
            elapsed = time.monotonic() - start_t

            failed_card = SubSessionProgressCard(
                task_id=task_id,
                meta_session_id=meta_session_id,
                title=title,
                status=SubSessionStatus.FAILED,
                current_step=f"Failed with {report.error_type}: {report.error_message}",
                elapsed_seconds=round(elapsed, 2),
                tokens_consumed=card.tokens_consumed if card else 0,
                completed_substeps=card.completed_substeps if card else [],
                active_tool="",
                updated_at_iso=datetime.now(timezone.utc).isoformat(),
            )
            self._cards[key] = failed_card
            return failed_card, report

    def get_progress_cards(self, meta_session_id: str) -> list[SubSessionProgressCard]:
        """Retrieve all sub-session progress cards belonging to a parent meta-session."""
        with self._lock:
            return [
                card
                for (m_id, _), card in self._cards.items()
                if m_id == meta_session_id
            ]

    def clear_session(self, meta_session_id: str) -> None:
        """Purge all progress cards and timers associated with a meta-session."""
        with self._lock:
            keys_to_delete = [k for k in self._cards if k[0] == meta_session_id]
            for k in keys_to_delete:
                self._cards.pop(k, None)
                self._start_times.pop(k, None)
            self._fault_isolator.clear_session(meta_session_id)

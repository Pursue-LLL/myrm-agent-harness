# [INPUT]: DualTrackMemoryBus, format_dual_track_prompt_block from dual_track_memory_bus, HierarchicalMetaSessionOrchestrator, format_meta_progress_hud from hierarchical_meta_orchestrator, MetaSessionConfig, SubSessionFailureReport, SubSessionHandoffDigest, SubSessionProgressCard, SubSessionTaskDescriptor from orchestration_types, SubSessionFaultIsolator from sub_session_fault_isolator
# [OUTPUT]: MetaSessionOrchestrationAndChatCoworkDualTrackFusionSuite
# [POS]: myrm_agent_harness.agent.context_management.meta_session_orchestration.meta_session_fusion_suite
"""Unified facade suite for Meta-Session Orchestration & Dual-Track Fusion (Item 332).

Coordinates cascading parent-child session orchestration, Chat & Cowork bidirectional
memory bridging, sub-session crash isolation, and realtime progress HUD streaming.
"""

from __future__ import annotations

import threading
from typing import Final

from myrm_agent_harness.agent.context_management.meta_session_orchestration.dual_track_memory_bus import (
    DualTrackMemoryBus,
    format_dual_track_prompt_block,
)
from myrm_agent_harness.agent.context_management.meta_session_orchestration.hierarchical_meta_orchestrator import (
    HierarchicalMetaSessionOrchestrator,
    format_meta_progress_hud,
)
from myrm_agent_harness.agent.context_management.meta_session_orchestration.orchestration_types import (
    MetaSessionConfig,
    SubSessionFailureReport,
    SubSessionHandoffDigest,
    SubSessionProgressCard,
    SubSessionTaskDescriptor,
)
from myrm_agent_harness.agent.context_management.meta_session_orchestration.sub_session_fault_isolator import (
    SubSessionFaultIsolator,
)


class MetaSessionOrchestrationAndChatCoworkDualTrackFusionSuite:
    """Industrial facade providing end-to-end meta-session dispatch, dual-track memory, and crash isolation."""

    def __init__(self, config: MetaSessionConfig | None = None) -> None:
        self._lock = threading.RLock()
        self._config: Final[MetaSessionConfig] = config or MetaSessionConfig()
        self._fault_isolator: Final[SubSessionFaultIsolator] = SubSessionFaultIsolator()
        self._memory_bus: Final[DualTrackMemoryBus] = DualTrackMemoryBus()
        self._orchestrator: Final[HierarchicalMetaSessionOrchestrator] = (
            HierarchicalMetaSessionOrchestrator(
                config=self._config,
                fault_isolator=self._fault_isolator,
            )
        )

    @property
    def config(self) -> MetaSessionConfig:
        """Active suite configuration."""
        return self._config

    @property
    def memory_bus(self) -> DualTrackMemoryBus:
        """Underlying Chat & Cowork dual-track memory bus."""
        return self._memory_bus

    @property
    def orchestrator(self) -> HierarchicalMetaSessionOrchestrator:
        """Underlying hierarchical meta-session orchestrator."""
        return self._orchestrator

    @property
    def fault_isolator(self) -> SubSessionFaultIsolator:
        """Underlying worker sub-session fault isolator."""
        return self._fault_isolator

    def dispatch_worker_task(
        self,
        descriptor: SubSessionTaskDescriptor,
        chat_intent_projection: str = "",
        user_preferences: dict[str, str] | None = None,
        constraints: list[str] | None = None,
    ) -> SubSessionProgressCard:
        """Dispatch a worker sub-session, optionally projecting Chat context into the memory bus.

        Args:
            descriptor: Sub-session task definition.
            chat_intent_projection: Optional user intent summary from parent chat.
            user_preferences: Optional user preferences to inject into worker track.
            constraints: Non-negotiable requirements to anchor in worker memory.

        Returns:
            Initial SubSessionProgressCard.
        """
        with self._lock:
            if chat_intent_projection:
                self._memory_bus.project_chat_to_cowork(
                    meta_session_id=descriptor.meta_session_id,
                    user_intent=chat_intent_projection,
                    preferences=user_preferences,
                    constraints=constraints,
                    working_summary=descriptor.goal_description,
                )

            return self._orchestrator.dispatch_sub_session(descriptor)

    def update_task_progress(
        self,
        meta_session_id: str,
        task_id: str,
        current_step: str,
        active_tool: str = "",
        tokens_consumed: int = 0,
        completed_substep: str = "",
    ) -> SubSessionProgressCard:
        """Update live execution progress for an active worker sub-session."""
        return self._orchestrator.update_sub_session_progress(
            meta_session_id=meta_session_id,
            task_id=task_id,
            current_step=current_step,
            active_tool=active_tool,
            tokens_consumed=tokens_consumed,
            add_completed_substep=completed_substep,
        )

    def complete_worker_task(
        self,
        meta_session_id: str,
        task_id: str,
        outcome_summary: str,
        deliverables: list[str] | None = None,
        lessons_learned: list[str] | None = None,
    ) -> tuple[SubSessionProgressCard, SubSessionHandoffDigest]:
        """Mark worker sub-session as complete, optionally sinking deliverable brief into memory bus."""
        card, digest = self._orchestrator.complete_sub_session(
            meta_session_id=meta_session_id,
            task_id=task_id,
            outcome_summary=outcome_summary,
            deliverables=deliverables,
            lessons_learned=lessons_learned,
        )

        if self._config.auto_sink_on_completion:
            with self._lock:
                self._memory_bus.sink_cowork_to_meta(
                    meta_session_id=meta_session_id,
                    handoff_digest=digest,
                )

        return card, digest

    def fail_worker_task(
        self,
        meta_session_id: str,
        task_id: str,
        exc: Exception,
    ) -> tuple[SubSessionProgressCard, SubSessionFailureReport]:
        """Isolate worker sub-session exception, returning failed card and diagnostic report."""
        return self._orchestrator.fail_sub_session(
            meta_session_id=meta_session_id,
            task_id=task_id,
            exc=exc,
        )

    def get_meta_progress_hud(self, meta_session_id: str) -> str:
        """Format active progress cards for a meta-session into Markdown HUD."""
        cards = self._orchestrator.get_progress_cards(meta_session_id)
        return format_meta_progress_hud(cards)

    def get_dual_track_memory_prompt(self, meta_session_id: str) -> str:
        """Format shared dual-track memory envelopes into Markdown prompt evidence block."""
        envelopes = self._memory_bus.get_envelopes(meta_session_id)
        return format_dual_track_prompt_block(envelopes)

    def clear_session(self, meta_session_id: str) -> None:
        """Purge all memory envelopes, progress cards, and timers for a session."""
        with self._lock:
            self._memory_bus.clear_session(meta_session_id)
            self._orchestrator.clear_session(meta_session_id)

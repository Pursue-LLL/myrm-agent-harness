# [INPUT]: DualTrackMemoryEnvelope, SessionTrackMode, SubSessionHandoffDigest, compute_envelope_hash from orchestration_types
# [OUTPUT]: DualTrackMemoryBus, format_dual_track_prompt_block
# [POS]: myrm_agent_harness.agent.context_management.meta_session_orchestration.dual_track_memory_bus
"""Chat & Cowork Dual-Track Unified Memory and State Bus (Item 332).

Ensures bidirectional, lossless memory flow between lightweight conversational chat
and deep-dive execution cowork modes without history cross-contamination.
"""

from __future__ import annotations

import threading
import uuid
from typing import Final

from myrm_agent_harness.agent.context_management.meta_session_orchestration.orchestration_types import (
    DualTrackMemoryEnvelope,
    SessionTrackMode,
    SubSessionHandoffDigest,
    compute_envelope_hash,
)


def format_dual_track_prompt_block(envelopes: list[DualTrackMemoryEnvelope]) -> str:
    """Format stored memory envelopes into an authoritative system prompt injection block."""
    if not envelopes:
        return ""

    lines: list[str] = [
        "=== DUAL-TRACK UNIFIED MEMORY BUS EVIDENCE ===",
        "Authoritative shared memories between Chat & Cowork modes for this session:",
    ]
    for idx, env in enumerate(envelopes, 1):
        lines.append(f"[{idx}] Source Track: {env.track_mode.value.upper()}")
        lines.append(f"    Intent: {env.user_intent}")
        if env.preferences:
            pref_strs = [f"{k}={v}" for k, v in env.preferences.items()]
            lines.append(f"    Preferences: {', '.join(pref_strs)}")
        if env.active_constraints:
            lines.append(f"    Constraints: {'; '.join(env.active_constraints)}")
        lines.append(f"    Working Summary: {env.working_summary}")
        if env.generated_artifacts:
            lines.append(f"    Artifacts: {', '.join(env.generated_artifacts)}")
    lines.append("===============================================")
    return "\n".join(lines)


class DualTrackMemoryBus:
    """Thread-safe state bus coordinating bidirectional memory synchronization across modes."""

    def __init__(self, max_envelopes_per_session: int = 50) -> None:
        self._lock = threading.RLock()
        self._max_envelopes: Final[int] = max_envelopes_per_session
        # meta_session_id -> list of DualTrackMemoryEnvelope
        self._store: dict[str, list[DualTrackMemoryEnvelope]] = {}

    def project_chat_to_cowork(
        self,
        meta_session_id: str,
        user_intent: str,
        preferences: dict[str, str] | None = None,
        constraints: list[str] | None = None,
        working_summary: str = "",
    ) -> DualTrackMemoryEnvelope:
        """Extract high-density intentions and constraints from Chat and project into Cowork.

        Args:
            meta_session_id: Parent conversation session identifier.
            user_intent: Synthesized task target.
            preferences: Explicit user styling and configuration preferences.
            constraints: Non-negotiable requirements and boundaries.
            working_summary: High-density narrative of current working state.

        Returns:
            Sealed DualTrackMemoryEnvelope ready for sub-session injection.
        """
        pref = preferences or {}
        consts = constraints or []
        summary = working_summary or f"Chat Intent Projection: {user_intent}"
        env_hash = compute_envelope_hash(
            meta_session_id=meta_session_id,
            user_intent=user_intent,
            working_summary=summary,
            track_mode=SessionTrackMode.CHAT,
        )

        envelope = DualTrackMemoryEnvelope(
            envelope_id=f"env_chat_{uuid.uuid4().hex[:12]}",
            meta_session_id=meta_session_id,
            track_mode=SessionTrackMode.CHAT,
            user_intent=user_intent,
            preferences=pref,
            active_constraints=consts,
            working_summary=summary,
            generated_artifacts=[],
            envelope_hash=env_hash,
        )

        with self._lock:
            envelopes = self._store.setdefault(meta_session_id, [])
            envelopes.append(envelope)
            if len(envelopes) > self._max_envelopes:
                self._store[meta_session_id] = envelopes[-self._max_envelopes :]

        return envelope

    def sink_cowork_to_meta(
        self,
        meta_session_id: str,
        handoff_digest: SubSessionHandoffDigest,
    ) -> DualTrackMemoryEnvelope:
        """Atomically persist deep-dive Cowork deliverables back into parent Meta memory.

        Args:
            meta_session_id: Parent meta-session identifier.
            handoff_digest: Delivered brief containing deliverables and outcome summary.

        Returns:
            Sealed DualTrackMemoryEnvelope anchoring the sub-session delivery.
        """
        summary = (
            f"Delivered Task '{handoff_digest.title}': {handoff_digest.outcome_summary}"
        )
        env_hash = compute_envelope_hash(
            meta_session_id=meta_session_id,
            user_intent=f"Complete sub-task {handoff_digest.task_id}",
            working_summary=summary,
            track_mode=SessionTrackMode.COWORK,
        )

        envelope = DualTrackMemoryEnvelope(
            envelope_id=f"env_cowork_{uuid.uuid4().hex[:12]}",
            meta_session_id=meta_session_id,
            track_mode=SessionTrackMode.COWORK,
            user_intent=f"Outcome of {handoff_digest.title}",
            preferences={},
            active_constraints=[],
            working_summary=summary,
            generated_artifacts=handoff_digest.deliverables,
            envelope_hash=env_hash,
        )

        with self._lock:
            envelopes = self._store.setdefault(meta_session_id, [])
            envelopes.append(envelope)
            if len(envelopes) > self._max_envelopes:
                self._store[meta_session_id] = envelopes[-self._max_envelopes :]

        return envelope

    def get_envelopes(self, meta_session_id: str) -> list[DualTrackMemoryEnvelope]:
        """Retrieve all stored envelopes for the specified meta-session in chronological order."""
        with self._lock:
            return list(self._store.get(meta_session_id, []))

    def clear_session(self, meta_session_id: str) -> None:
        """Purge stored memory envelopes for a meta-session."""
        with self._lock:
            self._store.pop(meta_session_id, None)

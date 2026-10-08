"""Suite managing append-only session event sourcing, step replaying, and audit certificates."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .append_only_event_log import AppendOnlyEventLog
from .deterministic_context_projector import DeterministicContextProjector
from .event_sourcing_types import (
    ContextReplayCertificate,
    ProjectedModelVisibleContext,
    SessionEventKind,
    SessionLedgerEvent,
)


class AppendOnlySessionEventSourcingAndContextReplayerSuite:
    """Orchestrates immutable event sourcing, pure functional projections, and step replayer."""

    def __init__(
        self,
        event_log: Optional[AppendOnlyEventLog] = None,
        projector: Optional[DeterministicContextProjector] = None,
    ) -> None:
        self._log = event_log or AppendOnlyEventLog()
        self._projector = projector or DeterministicContextProjector()

    @property
    def event_log(self) -> AppendOnlyEventLog:
        """Access underlying append-only event log."""
        return self._log

    @property
    def projector(self) -> DeterministicContextProjector:
        """Access underlying context projector."""
        return self._projector

    def record_user_prompt(self, session_id: str, prompt: str) -> SessionLedgerEvent:
        """Record user prompt event."""
        return self._log.append_event(session_id, SessionEventKind.USER_PROMPT, {"prompt": prompt})

    def record_system_directive(self, session_id: str, directive: str) -> SessionLedgerEvent:
        """Record injected system directive event."""
        return self._log.append_event(
            session_id, SessionEventKind.SYSTEM_DIRECTIVE_INJECTED, {"directive": directive}
        )

    def record_assistant_reply(self, session_id: str, reply: str) -> SessionLedgerEvent:
        """Record assistant response event."""
        return self._log.append_event(session_id, SessionEventKind.ASSISTANT_REPLY, {"reply": reply})

    def record_tool_result(
        self, session_id: str, tool_name: str, result: str, tool_call_id: Optional[str] = None
    ) -> SessionLedgerEvent:
        """Record tool execution result event."""
        payload = {"tool_name": tool_name, "result": result}
        if tool_call_id:
            payload["tool_call_id"] = tool_call_id
        return self._log.append_event(session_id, SessionEventKind.TOOL_RESULT, payload)

    def record_context_compaction(self, session_id: str, summary: str) -> SessionLedgerEvent:
        """Record context compaction summary event."""
        return self._log.append_event(session_id, SessionEventKind.CONTEXT_COMPACTED, {"summary": summary})

    def record_rule_update(self, session_id: str, rules_digest: str) -> SessionLedgerEvent:
        """Record rule update event."""
        return self._log.append_event(session_id, SessionEventKind.RULE_UPDATED, {"rules_digest": rules_digest})

    def replay_context_at_step(
        self,
        session_id: str,
        target_sequence: int,
    ) -> ProjectedModelVisibleContext:
        """Replay and project exact model-visible context at target sequence number."""
        events = self._log.get_events(session_id, up_to_sequence=target_sequence)
        return self._projector.project_at_sequence(events, target_sequence)

    def generate_replay_certificate(
        self,
        session_id: str,
        target_sequence: int,
    ) -> ContextReplayCertificate:
        """Verify deterministic replay by double-projection and issue audit certificate."""
        events = self._log.get_events(session_id, up_to_sequence=target_sequence)

        # Double projection to verify absolute determinism
        proj1 = self._projector.project_at_sequence(events, target_sequence)
        proj2 = self._projector.project_at_sequence(events, target_sequence)
        is_deterministic = proj1.context_digest == proj2.context_digest

        now_iso = datetime.now(timezone.utc).isoformat()
        return ContextReplayCertificate(
            session_id=session_id,
            target_sequence=target_sequence,
            events_replayed_count=len(events),
            projection_digest=proj1.context_digest,
            is_deterministic=is_deterministic,
            timestamp_iso=now_iso,
        )

    def diff_context_between_steps(
        self,
        session_id: str,
        seq_a: int,
        seq_b: int,
    ) -> Dict[str, object]:
        """Compute structural difference between two historical context steps."""
        proj_a = self.replay_context_at_step(session_id, seq_a)
        proj_b = self.replay_context_at_step(session_id, seq_b)

        return {
            "session_id": session_id,
            "step_a": seq_a,
            "step_b": seq_b,
            "digest_a": proj_a.context_digest,
            "digest_b": proj_b.context_digest,
            "messages_count_a": len(proj_a.visible_messages),
            "messages_count_b": len(proj_b.visible_messages),
            "system_prompt_changed": proj_a.effective_system_prompt != proj_b.effective_system_prompt,
            "compaction_triggered": not proj_a.compaction_applied and proj_b.compaction_applied,
        }

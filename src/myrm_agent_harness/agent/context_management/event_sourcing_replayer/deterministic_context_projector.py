"""Pure functional projector deriving exact model-visible context from event stream slices.

[INPUT]
- agent.context_management.event_sourcing_replayer.event_sourcing_types::ProjectedMessageItem,
  ProjectedModelVisibleContext, SessionEventKind, SessionLedgerEvent (POS: Types and models for append-only
  session event sourcing and deterministic context replaying.)

[OUTPUT]
- DeterministicContextProjector: Pure functional projector converting immutable event slices into historical
  model-visible contexts.

[POS]
Pure functional projector deriving exact model-visible context from event stream slices.
"""

from __future__ import annotations

import hashlib
from typing import List

from .event_sourcing_types import (
    ProjectedMessageItem,
    ProjectedModelVisibleContext,
    SessionEventKind,
    SessionLedgerEvent,
)


class DeterministicContextProjector:
    """Pure functional projector converting immutable event slices into historical model-visible contexts."""

    def project_at_sequence(
        self,
        events: List[SessionLedgerEvent],
        target_sequence: int,
    ) -> ProjectedModelVisibleContext:
        """Derive model-visible context up to target_sequence as a pure function of event stream."""
        if not events:
            return ProjectedModelVisibleContext(
                session_id="empty",
                target_sequence=target_sequence,
                effective_system_prompt="Base System",
                visible_messages=[],
                context_digest="empty",
            )

        session_id = events[0].session_id
        filtered_events = [e for e in events if e.sequence_number <= target_sequence]

        system_prompt = "You are Myrm Agent."
        visible_messages: List[ProjectedMessageItem] = []
        rules_digest = "default-rules"
        compaction_applied = False

        for event in filtered_events:
            kind = event.kind
            payload = event.payload

            if kind == SessionEventKind.SYSTEM_DIRECTIVE_INJECTED:
                directive = payload.get("directive", "")
                system_prompt = f"{system_prompt}\n{directive}".strip()

            elif kind == SessionEventKind.USER_PROMPT:
                visible_messages.append(
                    ProjectedMessageItem(
                        role="user",
                        content=payload.get("prompt", ""),
                        step_sequence=event.sequence_number,
                    )
                )

            elif kind == SessionEventKind.ASSISTANT_REPLY:
                visible_messages.append(
                    ProjectedMessageItem(
                        role="assistant",
                        content=payload.get("reply", ""),
                        step_sequence=event.sequence_number,
                    )
                )

            elif kind == SessionEventKind.TOOL_RESULT:
                visible_messages.append(
                    ProjectedMessageItem(
                        role="tool",
                        content=payload.get("result", ""),
                        step_sequence=event.sequence_number,
                        tool_call_id=payload.get("tool_call_id"),
                    )
                )

            elif kind == SessionEventKind.CONTEXT_COMPACTED:
                summary = payload.get("summary", "")
                compaction_applied = True
                # Replace history with compacted summary
                visible_messages = [
                    ProjectedMessageItem(
                        role="system",
                        content=f"[Context Summary]: {summary}",
                        step_sequence=event.sequence_number,
                    )
                ]

            elif kind == SessionEventKind.RULE_UPDATED:
                rules_digest = payload.get("rules_digest", rules_digest)

        # Compute deterministic fingerprint of visible context
        msg_repr = "".join(f"{m.role}:{m.content}:{m.step_sequence}" for m in visible_messages)
        context_fingerprint = f"{session_id}:{target_sequence}:{system_prompt}:{msg_repr}:{rules_digest}"
        digest = hashlib.sha256(context_fingerprint.encode("utf-8")).hexdigest()[:16]

        return ProjectedModelVisibleContext(
            session_id=session_id,
            target_sequence=target_sequence,
            effective_system_prompt=system_prompt,
            visible_messages=visible_messages,
            active_rules_digest=rules_digest,
            compaction_applied=compaction_applied,
            context_digest=digest,
        )

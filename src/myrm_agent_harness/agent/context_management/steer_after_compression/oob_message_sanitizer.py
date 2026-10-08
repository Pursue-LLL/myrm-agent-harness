"""Sanitization engine filtering out-of-band management messages from replay contexts.

[INPUT]
- agent.context_management.steer_after_compression.steer_compression_types::ContextTurnMessage,
  SanitizedReplayResult, SteerMessageKind (POS: Strongly typed domain models for turn messages and replay results.)

[OUTPUT]
- OOBMessageSanitizer: Manages durable persistence of all turns while cleanly stripping
  out-of-band steer and stop directives during prompt replay assembly.

[POS]
Replay context hygiene engine stripping out-of-band management controls.
"""

from __future__ import annotations

import hashlib
import json
import time

from .steer_compression_types import (
    ContextTurnMessage,
    SanitizedReplayResult,
    SteerMessageKind,
)


class OOBMessageSanitizer:
    """Maintains durable audit persistence while stripping OOB messages from replay context."""

    def __init__(self) -> None:
        # session_id -> list of persisted messages
        self._persisted_store: dict[str, list[ContextTurnMessage]] = {}

    def append_message(
        self,
        session_id: str,
        message_id: str,
        role: str,
        content: str,
        is_oob: bool = False,
        kind: SteerMessageKind = SteerMessageKind.IN_BAND_PROMPT,
        metadata: dict[str, str] | None = None,
    ) -> ContextTurnMessage:
        """Persist a message turn durably in session audit history.

        Args:
            session_id: Target session identifier.
            message_id: Unique message identifier.
            role: Speaker role (e.g., 'user', 'assistant', 'system').
            content: Natural language or directive text.
            is_oob: Whether the message is an out-of-band control directive.
            kind: Category of the steering message.
            metadata: Optional metadata attributes.

        Returns:
            The created ContextTurnMessage.
        """
        # Auto-detect explicit OOB markers
        resolved_oob = is_oob or kind in (
            SteerMessageKind.OUT_OF_BAND_STEER,
            SteerMessageKind.OUT_OF_BAND_STOP,
        )
        if content.startswith("[OOB]") or content.startswith("[STOP]"):
            resolved_oob = True

        msg = ContextTurnMessage(
            message_id=message_id,
            role=role,
            content=content,
            is_oob=resolved_oob,
            kind=kind,
            created_at_utc=time.time(),
            metadata=dict(metadata or {}),
        )

        if session_id not in self._persisted_store:
            self._persisted_store[session_id] = []
        self._persisted_store[session_id].append(msg)
        return msg

    def sanitize_for_replay(self, session_id: str) -> SanitizedReplayResult:
        """Strip all out-of-band messages for clean model prompt replay assembly.

        Args:
            session_id: Identifier of the session to assemble.

        Returns:
            SanitizedReplayResult containing only in-band conversation turns.
        """
        all_messages = self._persisted_store.get(session_id, [])
        sanitized: list[ContextTurnMessage] = []
        stripped_count = 0

        for m in all_messages:
            if m.is_oob:
                stripped_count += 1
            else:
                sanitized.append(m)

        # Compute deterministic audit digest of sanitized content
        content_items = [f"{m.role}:{m.content}" for m in sanitized]
        payload = json.dumps(content_items, ensure_ascii=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        return SanitizedReplayResult(
            sanitized_messages=sanitized,
            total_persisted_count=len(all_messages),
            stripped_oob_count=stripped_count,
            is_clean=stripped_count > 0 or len(all_messages) == len(sanitized),
            audit_digest=digest,
        )

    def get_persisted_history(self, session_id: str) -> list[ContextTurnMessage]:
        """Retrieve full un-sanitized audit history including OOB directives."""
        return list(self._persisted_store.get(session_id, []))

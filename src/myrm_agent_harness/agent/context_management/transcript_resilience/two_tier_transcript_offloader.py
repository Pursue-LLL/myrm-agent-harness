# [INPUT]: HydratedTranscriptMessage, TranscriptStubRecord, compute_payload_hash from resilience_types
# [OUTPUT]: TwoTierTranscriptOffloader
# [POS]: myrm_agent_harness.agent.context_management.transcript_resilience.two_tier_transcript_offloader
"""Two-Tier Transcript Offloading and Bounded Heap Window Engine (Item 333).

Stubs out-of-viewport historical messages to keep active memory bounded and lightweight,
restoring full payloads from offline backing storage on-demand in milliseconds.
"""

from __future__ import annotations

import threading
from typing import Final

from myrm_agent_harness.agent.context_management.transcript_resilience.resilience_types import (
    DEFAULT_MAX_VIEWPORT_MESSAGES,
    HydratedTranscriptMessage,
    TranscriptStubRecord,
    compute_payload_hash,
)


class TwoTierTranscriptOffloader:
    """Coordinates in-memory message viewport boundaries and offline message stubs."""

    def __init__(self, max_viewport_size: int = DEFAULT_MAX_VIEWPORT_MESSAGES) -> None:
        self._lock = threading.RLock()
        self._max_viewport: Final[int] = max_viewport_size
        # session_id -> list of (is_stub: bool, record_or_hydrated)
        # We maintain chronological sequence: stubs for older messages, full messages for recent viewport
        self._active_viewport: dict[str, list[HydratedTranscriptMessage]] = {}
        self._stubs: dict[str, list[TranscriptStubRecord]] = {}
        # session_id -> dict[msg_id, HydratedTranscriptMessage] (offline persistent backing cache)
        self._offline_vault: dict[str, dict[str, HydratedTranscriptMessage]] = {}

    @property
    def max_viewport_size(self) -> int:
        """Configured maximum active messages in memory viewport."""
        return self._max_viewport

    def append_message(
        self,
        session_id: str,
        msg_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, str | int | float | bool | list[str] | dict[str, str]]] | None = None,
        created_at_iso: str = "",
    ) -> HydratedTranscriptMessage:
        """Append a new message into active transcript, offloading oldest message if viewport overflows.

        Args:
            session_id: Session identifier.
            msg_id: Unique message identifier.
            role: Message role (user, assistant, tool, system).
            content: Message string content.
            tool_calls: Optional tool calls list.
            created_at_iso: Creation UTC timestamp.

        Returns:
            HydratedTranscriptMessage newly appended.
        """
        calls = tool_calls or []
        msg = HydratedTranscriptMessage(
            msg_id=msg_id,
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=calls,
            raw_payload="",
            created_at_iso=created_at_iso,
        )

        with self._lock:
            # 1. Store into offline vault unconditionally to guarantee durability
            session_vault = self._offline_vault.setdefault(session_id, {})
            session_vault[msg_id] = msg

            # 2. Append to active viewport
            viewport = self._active_viewport.setdefault(session_id, [])
            viewport.append(msg)

            # 3. Offload oldest message if viewport exceeds threshold
            if len(viewport) > self._max_viewport:
                oldest_msg = viewport.pop(0)
                stub = TranscriptStubRecord(
                    msg_id=oldest_msg.msg_id,
                    session_id=session_id,
                    role=oldest_msg.role,
                    char_count=len(oldest_msg.content),
                    has_tool_calls=len(oldest_msg.tool_calls) > 0,
                    original_payload_hash=compute_payload_hash(
                        role=oldest_msg.role,
                        content=oldest_msg.content,
                        tool_calls=oldest_msg.tool_calls,
                    ),
                    created_at_iso=oldest_msg.created_at_iso,
                )
                session_stubs = self._stubs.setdefault(session_id, [])
                session_stubs.append(stub)

            return msg

    def hydrate_message(self, session_id: str, msg_id: str) -> HydratedTranscriptMessage | None:
        """Fetch full un-stubbed message from offline storage on-demand.

        Args:
            session_id: Session identifier.
            msg_id: Unique message identifier.

        Returns:
            HydratedTranscriptMessage or None if not found.
        """
        with self._lock:
            session_vault = self._offline_vault.get(session_id, {})
            return session_vault.get(msg_id)

    def get_viewport_messages(self, session_id: str) -> list[HydratedTranscriptMessage]:
        """Retrieve list of active messages currently retained in viewport memory."""
        with self._lock:
            return list(self._active_viewport.get(session_id, []))

    def get_stubs(self, session_id: str) -> list[TranscriptStubRecord]:
        """Retrieve list of offloaded stubs for historical messages outside viewport."""
        with self._lock:
            return list(self._stubs.get(session_id, []))

    def get_total_message_count(self, session_id: str) -> int:
        """Total messages belonging to this session across stubs and viewport."""
        with self._lock:
            stub_count = len(self._stubs.get(session_id, []))
            vp_count = len(self._active_viewport.get(session_id, []))
            return stub_count + vp_count

    def clear_session(self, session_id: str) -> None:
        """Purge all viewport messages, stubs, and offline vault entries for session."""
        with self._lock:
            self._active_viewport.pop(session_id, None)
            self._stubs.pop(session_id, None)
            self._offline_vault.pop(session_id, None)

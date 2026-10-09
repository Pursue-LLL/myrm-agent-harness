"""Stream terminal event watchdog and silent end anomaly detector.

[INPUT]
- silent_end_types: SilentEndReconcileConfig, SilentEndTicket, TerminalEventKind.

[OUTPUT]
- StreamTerminalWatchdog: Monitors SSE message stream consumption, detecting
  truncated runs where transport terminated without business terminal events.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.silent_end_reconcile
- Module: stream_terminal_watchdog.py
"""

import time
from typing import Dict, List, Optional, Set

from myrm_agent_harness.agent.context_management.silent_end_reconcile.silent_end_types import (
    SilentEndReconcileConfig,
    SilentEndTicket,
)


class StreamTerminalWatchdog:
    """Monitors incoming SSE stream chunks to spot truncated runs lacking terminal events."""

    def __init__(self, config: Optional[SilentEndReconcileConfig] = None) -> None:
        self._config = config or SilentEndReconcileConfig()
        self._received_terminals: Set[str] = set()
        self._chunk_counts: Dict[str, int] = {}
        self._last_event_ids: Dict[str, str] = {}

    def register_stream_start(self, session_id: str, run_id: str) -> None:
        """Initializes tracking for a newly initiated SSE stream turn."""
        key = self._format_key(session_id, run_id)
        self._received_terminals.discard(key)
        self._chunk_counts[key] = 0
        self._last_event_ids.pop(key, None)

    def record_chunk_event(
        self,
        session_id: str,
        run_id: str,
        event_name: str,
        event_id: Optional[str] = None,
    ) -> None:
        """Records an incoming SSE event chunk and checks for recognized terminal signatures."""
        key = self._format_key(session_id, run_id)
        self._chunk_counts[key] = self._chunk_counts.get(key, 0) + 1
        if event_id is not None:
            self._last_event_ids[key] = event_id

        if event_name in self._config.recognized_terminal_events:
            self._received_terminals.add(key)

    def on_stream_transport_completed(
        self,
        session_id: str,
        run_id: str,
        transport_reason: str = "HTTP EOF reached",
    ) -> Optional[SilentEndTicket]:
        """Evaluates stream closure upon transport completion (e.g. reader.read().done == true).

        Args:
            session_id: Target session identifier.
            run_id: Specific agent execution turn identifier.
            transport_reason: Message indicating how the underlying transport completed.

        Returns:
            SilentEndTicket if stream closed prematurely without terminal envelope; else None.
        """
        key = self._format_key(session_id, run_id)
        has_terminal = key in self._received_terminals
        chunks = self._chunk_counts.get(key, 0)
        last_id = self._last_event_ids.get(key)

        if has_terminal:
            # Stream finished authentically with proper terminal event
            return None

        # Silent end detected: stream ended without terminal envelope
        now_epoch = time.time()
        return SilentEndTicket(
            session_id=session_id,
            run_id=run_id,
            last_event_id=last_id,
            total_chunks_received=chunks,
            detected_at_epoch=now_epoch,
            raw_interruption_reason=transport_reason,
        )

    def has_terminal_received(self, session_id: str, run_id: str) -> bool:
        """Returns True if the specified turn received a business terminal envelope."""
        key = self._format_key(session_id, run_id)
        return key in self._received_terminals

    def reset_turn(self, session_id: str, run_id: str) -> None:
        """Cleans up internal state for a completed turn."""
        key = self._format_key(session_id, run_id)
        self._received_terminals.discard(key)
        self._chunk_counts.pop(key, None)
        self._last_event_ids.pop(key, None)

    @staticmethod
    def _format_key(session_id: str, run_id: str) -> str:
        return f"{session_id}::{run_id}"

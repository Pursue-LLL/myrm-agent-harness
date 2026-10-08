"""Append-only immutable event log maintaining monotonic sequence numbers and hash chains.

[INPUT]
- agent.context_management.event_sourcing_replayer.event_sourcing_types::SessionEventKind, SessionLedgerEvent
  (POS: Types and models for append-only session event sourcing and deterministic context replaying.)

[OUTPUT]
- AppendOnlyEventLog: Manages append-only immutable event logs with tamper-evident cryptographic hash
  chaining.

[POS]
Append-only immutable event log maintaining monotonic sequence numbers and hash chains.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .event_sourcing_types import SessionEventKind, SessionLedgerEvent


class AppendOnlyEventLog:
    """Manages append-only immutable event logs with tamper-evident cryptographic hash chaining."""

    def __init__(self) -> None:
        self._events_by_session: Dict[str, List[SessionLedgerEvent]] = {}

    def append_event(
        self,
        session_id: str,
        kind: SessionEventKind,
        payload: Dict[str, str],
        causation_id: Optional[str] = None,
    ) -> SessionLedgerEvent:
        """Append an event with monotonically increasing sequence number and chained digest."""
        if session_id not in self._events_by_session:
            self._events_by_session[session_id] = []

        stream = self._events_by_session[session_id]
        seq_num = len(stream) + 1
        now_iso = datetime.now(timezone.utc).isoformat()

        prev_digest = stream[-1].event_digest if stream else "genesis"
        payload_repr = "".join(f"{k}:{v}" for k, v in sorted(payload.items()))
        hash_seed = f"{prev_digest}:{session_id}:{seq_num}:{kind.value}:{payload_repr}:{now_iso}"
        event_digest = hashlib.sha256(hash_seed.encode("utf-8")).hexdigest()[:16]
        event_id = f"evt-{session_id}-{seq_num}-{event_digest[:8]}"

        event = SessionLedgerEvent(
            event_id=event_id,
            session_id=session_id,
            sequence_number=seq_num,
            kind=kind,
            timestamp_iso=now_iso,
            payload=dict(payload),
            causation_id=causation_id,
            event_digest=event_digest,
        )

        stream.append(event)
        return event

    def get_events(
        self,
        session_id: str,
        up_to_sequence: Optional[int] = None,
    ) -> List[SessionLedgerEvent]:
        """Retrieve slice of events up to a given sequence number."""
        stream = self._events_by_session.get(session_id, [])
        if up_to_sequence is None:
            return list(stream)
        return [e for e in stream if e.sequence_number <= up_to_sequence]

    def verify_chain_integrity(self, session_id: str) -> bool:
        """Verify that the sequence numbers and hash links in the log have not been tampered with."""
        stream = self._events_by_session.get(session_id, [])
        if not stream:
            return True

        for idx, event in enumerate(stream):
            if event.sequence_number != idx + 1:
                return False
            prev_digest = stream[idx - 1].event_digest if idx > 0 else "genesis"
            payload_repr = "".join(f"{k}:{v}" for k, v in sorted(event.payload.items()))
            hash_seed = f"{prev_digest}:{event.session_id}:{event.sequence_number}:{event.kind.value}:{payload_repr}:{event.timestamp_iso}"
            expected_digest = hashlib.sha256(hash_seed.encode("utf-8")).hexdigest()[:16]
            if event.event_digest != expected_digest:
                return False

        return True

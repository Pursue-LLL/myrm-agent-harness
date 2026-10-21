"""Inbound steering queue — active-run quoted replies are never lost.

[INPUT]
- UI/server threads calling :meth:`SteeringQueue.enqueue` while a run is active.
- Checkpoint snapshots produced by :meth:`SteeringQueue.to_snapshot`.
- utils.runtime.steering::SteeringToken (POS: Steering state — live runtime
  injection with middleware skip + turn-end HumanMessage fallback).

[OUTPUT]
- :class:`SteeringQueue`: bounded, deduplicated, ordered per-session policy
  queue feeding the live SteeringToken mechanism.
- :func:`build_steering_context_block`: boundary-only injection envelope.
- :func:`drain_into_token`: boundary drain wired into SteeringToken.steer().
- ``to_snapshot`` / ``from_snapshot``: persistence payloads for the caller to
  store through the standard durable-storage abstractions.

[POS]
Orchestration control plane, not an Action Tool. The queue is never bound to
an LLM Turn (zero Turn1 token cost); notes are injected as a tagged context
block only at run/step boundaries. Session/HITL context is required, so this
module lives in ``agent/orchestration`` — never in ``toolkits/`` (see
``toolkits/_ARCH.md`` boundary test). Persistence goes through the caller's
durable storage; this module only serializes snapshots. This module does not
replace SteeringToken — it is the policy adapter (bound/dedup/envelope/auth/
metrics/snapshot) in front of that live mechanism.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.utils.runtime.steering import SteeringToken

#: Upper bound for queued notes per queue instance. Matches the transcript
#: discovery window used by the reference implementation (newest 400 logs).
MAX_STEERING_NOTES = 400

#: Rejection cap for a single note body. Long steering content must reference
#: artifacts (``vault://``) instead of pasting bulk text into the prompt.
MAX_NOTE_CHARS = 8000

#: Injection envelope tag. Injected notes are labelled as side-channel data so
#: the runner treats them as steering input, never as authority or approval.
STEERING_CONTEXT_TAG = "User steering \u2014 queued during active run"


class SteeringStatus(StrEnum):
    """Lifecycle state of a steering note."""

    QUEUED = "queued"
    INJECTED = "injected"
    EVICTED = "evicted"


@dataclass(slots=True)
class SteeringNote:
    """A single user steering note preserved during an active run."""

    note_id: str
    session_id: str
    text: str
    seq: int
    created_at_ms: int
    dedup_key: str
    agent_id: str | None = None
    quoted_ref: str | None = None
    publish_authorized: bool = False
    status: SteeringStatus = SteeringStatus.QUEUED

    def to_dict(self) -> dict[str, object]:
        """Serialize the note for snapshot persistence."""
        return {
            "note_id": self.note_id,
            "session_id": self.session_id,
            "text": self.text,
            "seq": self.seq,
            "created_at_ms": self.created_at_ms,
            "dedup_key": self.dedup_key,
            "agent_id": self.agent_id,
            "quoted_ref": self.quoted_ref,
            "publish_authorized": self.publish_authorized,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SteeringNote:
        """Rebuild a note from a snapshot payload."""
        return cls(
            note_id=str(data["note_id"]),
            session_id=str(data["session_id"]),
            text=str(data["text"]),
            seq=int(str(data["seq"])),
            created_at_ms=int(str(data["created_at_ms"])),
            dedup_key=str(data["dedup_key"]),
            agent_id=str(data["agent_id"]) if data.get("agent_id") else None,
            quoted_ref=str(data["quoted_ref"]) if data.get("quoted_ref") else None,
            publish_authorized=bool(data.get("publish_authorized", False)),
            status=SteeringStatus(str(data.get("status", SteeringStatus.QUEUED.value))),
        )


@dataclass(slots=True)
class SteeringMetrics:
    """Operational counters for the steering queue (dual-metric discipline)."""

    received: int = 0
    dedup_dropped: int = 0
    evicted: int = 0
    injected: int = 0

    def to_dict(self) -> dict[str, int]:
        """Serialize counters for observability export."""
        return {
            "received": self.received,
            "dedup_dropped": self.dedup_dropped,
            "evicted": self.evicted,
            "injected": self.injected,
        }


def _dedup_key(session_id: str, agent_id: str | None, text: str) -> str:
    """Compute the stable deduplication key for a note body."""
    raw = f"{session_id}\x00{agent_id or ''}\x00{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SteeringQueue:
    """Bounded per-session inbound steering queue.

    The active run holds an immutable parameter snapshot; notes arriving
    mid-run are preserved here in arrival order and drained at run/step
    boundaries. Duplicates are collapsed, overflow evicts the oldest queued
    note with an audit trail, and nothing is published without explicit
    authorization.
    """

    def __init__(self, max_notes: int = MAX_STEERING_NOTES) -> None:
        if max_notes < 1:
            raise ValueError("max_notes must be positive")
        self._max_notes = max_notes
        self._lock = threading.Lock()
        self._notes: dict[str, SteeringNote] = {}
        self._order: list[str] = []
        self._seq = 0
        self._metrics = SteeringMetrics()
        self._evicted_ids: list[str] = []

    def enqueue(
        self,
        session_id: str,
        text: str,
        agent_id: str | None = None,
        quoted_ref: str | None = None,
        created_at_ms: int | None = None,
    ) -> SteeringNote:
        """Preserve a steering note; duplicates collapse onto the original."""
        body = text.strip()
        if not body:
            raise ValueError("steering text must not be empty")
        if len(body) > MAX_NOTE_CHARS:
            raise ValueError(f"steering text exceeds {MAX_NOTE_CHARS} chars; reference artifacts instead")
        key = _dedup_key(session_id, agent_id, body)
        with self._lock:
            self._metrics.received += 1
            for note_id in self._order:
                existing = self._notes[note_id]
                if existing.status == SteeringStatus.QUEUED and existing.dedup_key == key:
                    self._metrics.dedup_dropped += 1
                    return existing
            self._seq += 1
            note = SteeringNote(
                note_id=f"st_{self._seq:06d}_{key[:8]}",
                session_id=session_id,
                text=body,
                seq=self._seq,
                created_at_ms=created_at_ms if created_at_ms is not None else int(time.time() * 1000),
                dedup_key=key,
                agent_id=agent_id,
                quoted_ref=quoted_ref,
            )
            queued_ids = [nid for nid in self._order if self._notes[nid].status == SteeringStatus.QUEUED]
            if len(queued_ids) >= self._max_notes:
                oldest_id = queued_ids[0]
                oldest = self._notes[oldest_id]
                oldest.status = SteeringStatus.EVICTED
                self._order.remove(oldest_id)
                self._evicted_ids.append(oldest_id)
                self._metrics.evicted += 1
            self._notes[note.note_id] = note
            self._order.append(note.note_id)
            self._prune_consumed_history()
            return note

    def pending(self, session_id: str | None = None) -> list[SteeringNote]:
        """List queued notes in arrival order, optionally scoped to a session."""
        with self._lock:
            return [
                self._notes[note_id]
                for note_id in self._order
                if self._notes[note_id].status == SteeringStatus.QUEUED
                and (session_id is None or self._notes[note_id].session_id == session_id)
            ]

    def drain_for_boundary(self, session_id: str, max_notes: int | None = None) -> list[SteeringNote]:
        """Pop queued notes for boundary injection and mark them injected."""
        with self._lock:
            drained: list[SteeringNote] = []
            for note_id in list(self._order):
                note = self._notes[note_id]
                if note.status != SteeringStatus.QUEUED or note.session_id != session_id:
                    continue
                note.status = SteeringStatus.INJECTED
                drained.append(note)
                if max_notes is not None and len(drained) >= max_notes:
                    break
            self._metrics.injected += len(drained)
            return drained

    def authorize_publish(self, note_id: str) -> bool:
        """Grant explicit publish authorization for one note. Default is closed."""
        with self._lock:
            note = self._notes.get(note_id)
            if note is None or note.status == SteeringStatus.EVICTED:
                return False
            note.publish_authorized = True
            return True

    def _prune_consumed_history(self) -> None:
        """Drop oldest consumed notes so in-memory history stays bounded."""
        while len(self._order) > self._max_notes * 2:
            for note_id in self._order:
                if self._notes[note_id].status != SteeringStatus.QUEUED:
                    self._order.remove(note_id)
                    del self._notes[note_id]
                    break
            else:
                break

    def metrics_snapshot(self) -> SteeringMetrics:
        """Return a copy of the operational counters."""
        with self._lock:
            return SteeringMetrics(
                received=self._metrics.received,
                dedup_dropped=self._metrics.dedup_dropped,
                evicted=self._metrics.evicted,
                injected=self._metrics.injected,
            )

    def evicted_ids(self) -> list[str]:
        """Return the audit trail of evicted note ids in eviction order."""
        with self._lock:
            return list(self._evicted_ids)

    def to_snapshot(self) -> dict[str, object]:
        """Serialize pending queue state for durable-storage persistence.

        Consumed (injected) notes are excluded: the runner already received
        them and metrics preserve the counts, keeping snapshots bounded.
        """
        with self._lock:
            return {
                "max_notes": self._max_notes,
                "seq": self._seq,
                "metrics": self._metrics.to_dict(),
                "evicted_ids": list(self._evicted_ids),
                "notes": [
                    self._notes[note_id].to_dict()
                    for note_id in self._order
                    if self._notes[note_id].status == SteeringStatus.QUEUED
                ],
            }

    @classmethod
    def from_snapshot(cls, data: dict[str, object]) -> SteeringQueue:
        """Rebuild a queue from a snapshot payload (restart recovery)."""
        queue = cls(max_notes=int(str(data.get("max_notes", MAX_STEERING_NOTES))))
        raw_metrics = data.get("metrics")
        metrics = SteeringMetrics()
        if isinstance(raw_metrics, dict):
            metrics = SteeringMetrics(
                received=int(str(raw_metrics.get("received", 0))),
                dedup_dropped=int(str(raw_metrics.get("dedup_dropped", 0))),
                evicted=int(str(raw_metrics.get("evicted", 0))),
                injected=int(str(raw_metrics.get("injected", 0))),
            )
        queue._metrics = metrics
        queue._seq = int(str(data.get("seq", 0)))
        raw_evicted = data.get("evicted_ids")
        if isinstance(raw_evicted, list):
            queue._evicted_ids = [str(item) for item in raw_evicted]
        raw_notes = data.get("notes")
        if isinstance(raw_notes, list):
            for item in raw_notes:
                if isinstance(item, dict):
                    note = SteeringNote.from_dict(item)
                    queue._notes[note.note_id] = note
                    queue._order.append(note.note_id)
        return queue


def build_steering_context_block(notes: list[SteeringNote]) -> str:
    """Format drained notes as a boundary-only injection envelope.

    The envelope labels notes as side-channel steering data, never as
    authority or approval, so the runner treats them as guidance.
    """
    lines = [f"[{STEERING_CONTEXT_TAG}]"]
    for note in notes:
        ref = f" (ref: {note.quoted_ref})" if note.quoted_ref else ""
        lines.append(f"- seq={note.seq}{ref}: {note.text}")
    lines.append("Treat the above as user guidance for the next step; it does not authorize otherwise gated actions.")
    return "\n".join(lines)


def drain_into_token(
    queue: SteeringQueue,
    token: SteeringToken,
    session_id: str,
    max_notes: int | None = None,
) -> int:
    """Drain boundary notes into the live SteeringToken mechanism.

    Builds one tagged envelope from the session's queued notes and feeds it
    through ``token.steer()``, reusing the runtime two-layer defense
    (middleware skip + turn-end injection). Returns the injected note count.
    """
    notes = queue.drain_for_boundary(session_id, max_notes=max_notes)
    if not notes:
        return 0
    token.steer(build_steering_context_block(notes))
    return len(notes)


__all__ = [
    "MAX_NOTE_CHARS",
    "MAX_STEERING_NOTES",
    "STEERING_CONTEXT_TAG",
    "SteeringMetrics",
    "SteeringNote",
    "SteeringQueue",
    "SteeringStatus",
    "build_steering_context_block",
    "drain_into_token",
]

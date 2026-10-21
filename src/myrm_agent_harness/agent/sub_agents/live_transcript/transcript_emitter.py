# -*- coding: utf-8 -*-
"""Subagent Live Transcript Emitter.

Emits human-readable structured telemetry for delegated subagents,
eliminating black-box wait times and enabling real-time UI tree rendering.

[INPUT]
- time
- typing
- threading
- types

[OUTPUT]
- TranscriptSubscriber
- MAX_PAYLOAD_STRING_LEN
- SubagentLiveTranscriptEmitter

[POS]
Subagent Live Transcript Emitter.
"""

import time
from typing import Callable, Dict, List, Optional
from threading import Lock

from .types import (
    JsonValue,
    SubagentTranscriptEvent,
    TranscriptEventKind,
)

# Callback type for real-time streaming listeners
TranscriptSubscriber = Callable[[SubagentTranscriptEvent], None]

MAX_PAYLOAD_STRING_LEN = 2048


def _sanitize_payload_value(val: JsonValue) -> JsonValue:
    """Truncate long string values in payloads to prevent buffer bloat."""
    if isinstance(val, str):
        if len(val) > MAX_PAYLOAD_STRING_LEN:
            return val[:MAX_PAYLOAD_STRING_LEN] + " ... [TRUNCATED]"
        return val
    if isinstance(val, list):
        return [_sanitize_payload_value(item) for item in val]
    if isinstance(val, dict):
        return {k: _sanitize_payload_value(v) for k, v in val.items()}
    return val


class SubagentLiveTranscriptEmitter:
    """Thread-safe live transcript event emitter for subagent execution."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._buffers: Dict[str, List[SubagentTranscriptEvent]] = {}
        self._subscribers: Dict[str, List[TranscriptSubscriber]] = {}
        self._global_subscribers: List[TranscriptSubscriber] = []

    def subscribe(
        self,
        task_id: Optional[str],
        subscriber: TranscriptSubscriber,
    ) -> None:
        """Subscribe to live events for a specific task_id or globally."""
        with self._lock:
            if task_id is None:
                self._global_subscribers.append(subscriber)
            else:
                if task_id not in self._subscribers:
                    self._subscribers[task_id] = []
                self._subscribers[task_id].append(subscriber)

    def unsubscribe(
        self,
        task_id: Optional[str],
        subscriber: TranscriptSubscriber,
    ) -> None:
        """Unsubscribe from live events."""
        with self._lock:
            if task_id is None:
                if subscriber in self._global_subscribers:
                    self._global_subscribers.remove(subscriber)
            else:
                if task_id in self._subscribers and subscriber in self._subscribers[task_id]:
                    self._subscribers[task_id].remove(subscriber)

    def emit(
        self,
        task_id: str,
        subagent_id: str,
        kind: TranscriptEventKind,
        human_readable: str,
        payload: Optional[Dict[str, JsonValue]] = None,
    ) -> SubagentTranscriptEvent:
        """Emit a new live transcript event and notify listeners."""
        with self._lock:
            if task_id not in self._buffers:
                self._buffers[task_id] = []

            seq = len(self._buffers[task_id]) + 1
            sanitized_payload: Dict[str, JsonValue] = {}
            if payload:
                for k, v in payload.items():
                    sanitized_payload[k] = _sanitize_payload_value(v)

            event = SubagentTranscriptEvent(
                task_id=task_id,
                subagent_id=subagent_id,
                seq=seq,
                timestamp=time.time(),
                kind=kind,
                human_readable=human_readable,
                payload=sanitized_payload,
            )
            self._buffers[task_id].append(event)
            task_listeners = list(self._subscribers.get(task_id, []))
            global_listeners = list(self._global_subscribers)

        # Notify callbacks outside the lock to prevent deadlocks
        for listener in task_listeners:
            try:
                listener(event)
            except Exception:
                pass
        for listener in global_listeners:
            try:
                listener(event)
            except Exception:
                pass

        return event

    def get_events(
        self,
        task_id: str,
        after_seq: int = 0,
        limit: Optional[int] = None,
    ) -> List[SubagentTranscriptEvent]:
        """Fetch recorded events for a task, optionally filtering after a sequence."""
        with self._lock:
            events = self._buffers.get(task_id, [])
            filtered = [e for e in events if e.seq > after_seq]
            if limit is not None:
                return filtered[:limit]
            return list(filtered)

    def clear(self, task_id: Optional[str] = None) -> None:
        """Clear event buffers for a specific task or all tasks."""
        with self._lock:
            if task_id:
                self._buffers.pop(task_id, None)
                self._subscribers.pop(task_id, None)
            else:
                self._buffers.clear()
                self._subscribers.clear()

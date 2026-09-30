"""Strongly-typed DTOs and enumerations for session-scoped loop scheduling.

[INPUT]
- Raw string arguments from /loop command
- LLM response content and turn status

[OUTPUT]
- LoopMode, LoopStatus, LoopStopReason enums
- LoopConfig, LoopState dataclasses

[POS]
Harness runtime layer. Defines pure data structures for loop parsing,
adaptive backoff, and stop condition validation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

#: Sentinel token emitted by model to signal completion of loop objective
LOOP_COMPLETE_MARKER: str = "LOOP_COMPLETE"

DEFAULT_MIN_INTERVAL_SECONDS: int = 30
DEFAULT_MAX_TICKS: int = 100
DEFAULT_SELF_PACED_FLOOR_SECONDS: int = 60
DEFAULT_SELF_PACED_CEILING_SECONDS: int = 15 * 60


class LoopMode(StrEnum):
    """Pacing mode for session loop."""

    INTERVAL = "interval"
    SELF_PACED = "self_paced"


class LoopStatus(StrEnum):
    """Lifecycle status of a session loop."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    CLEARED = "cleared"


class LoopStopReason(StrEnum):
    """Reason why a loop terminated or paused."""

    MODEL_SIGNAL = "model_signal"
    TIMES_EXHAUSTED = "times_exhausted"
    UNTIL_MET = "until_met"
    USER_STOPPED = "user_stopped"
    USER_PREEMPTED = "user_preempted"
    MAX_TICKS_REACHED = "max_ticks_reached"
    ERROR = "error"


@dataclass(frozen=True)
class LoopConfig:
    """Parsed configuration for a session loop command."""

    prompt: str
    interval_seconds: int | None = None
    times: int = 0
    until: str = ""
    error: str | None = None

    @property
    def is_valid(self) -> bool:
        """Return True if config has valid prompt and no parse error."""
        return bool(self.prompt) and self.error is None

    @property
    def mode(self) -> LoopMode:
        """Determine pacing mode based on interval presence."""
        return LoopMode.INTERVAL if self.interval_seconds is not None else LoopMode.SELF_PACED


@dataclass
class LoopState:
    """Serializable runtime state of an in-session loop."""

    session_id: str
    prompt: str
    status: LoopStatus = LoopStatus.ACTIVE
    mode: LoopMode = LoopMode.INTERVAL
    interval_seconds: float = float(DEFAULT_MIN_INTERVAL_SECONDS)
    current_delay: float = float(DEFAULT_SELF_PACED_FLOOR_SECONDS)
    times: int = 0
    until: str = ""
    max_ticks: int = DEFAULT_MAX_TICKS
    ticks_fired: int = 0
    created_at: float = 0.0
    last_fired_at: float = 0.0
    next_due_at: float = 0.0
    awaiting_response: bool = False
    last_response_digest: str = ""
    consecutive_unchanged: int = 0
    last_stop_reason: LoopStopReason | None = None
    paused_reason: str | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Convert state to dictionary for DB persistence."""
        data = asdict(self)
        data["status"] = self.status.value
        data["mode"] = self.mode.value
        if self.last_stop_reason is not None:
            data["last_stop_reason"] = self.last_stop_reason.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> LoopState:
        """Construct LoopState from serialized dictionary representation."""
        raw_status = str(data.get("status", LoopStatus.ACTIVE.value))
        try:
            status = LoopStatus(raw_status)
        except ValueError:
            status = LoopStatus.ACTIVE

        raw_mode = str(data.get("mode", LoopMode.INTERVAL.value))
        try:
            mode = LoopMode(raw_mode)
        except ValueError:
            mode = LoopMode.INTERVAL

        raw_stop = data.get("last_stop_reason")
        stop_reason: LoopStopReason | None = None
        if raw_stop:
            try:
                stop_reason = LoopStopReason(str(raw_stop))
            except ValueError:
                stop_reason = None

        raw_meta = data.get("extra_metadata")
        extra_meta = raw_meta if isinstance(raw_meta, dict) else {}

        return cls(
            session_id=str(data.get("session_id", "")),
            prompt=str(data.get("prompt", "")),
            status=status,
            mode=mode,
            interval_seconds=float(data.get("interval_seconds") or DEFAULT_MIN_INTERVAL_SECONDS),
            current_delay=float(data.get("current_delay") or DEFAULT_SELF_PACED_FLOOR_SECONDS),
            times=int(data.get("times") or 0),
            until=str(data.get("until") or ""),
            max_ticks=int(data.get("max_ticks") or DEFAULT_MAX_TICKS),
            ticks_fired=int(data.get("ticks_fired") or 0),
            created_at=float(data.get("created_at") or 0.0),
            last_fired_at=float(data.get("last_fired_at") or 0.0),
            next_due_at=float(data.get("next_due_at") or 0.0),
            awaiting_response=bool(data.get("awaiting_response", False)),
            last_response_digest=str(data.get("last_response_digest") or ""),
            consecutive_unchanged=int(data.get("consecutive_unchanged") or 0),
            last_stop_reason=stop_reason,
            paused_reason=str(data.get("paused_reason")) if data.get("paused_reason") else None,
            extra_metadata=extra_meta,
        )

    def to_json(self) -> str:
        """Serialize state to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> LoopState | None:
        """Deserialize LoopState from JSON string, returning None on error."""
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return cls.from_dict(parsed)
            return None
        except Exception:
            return None

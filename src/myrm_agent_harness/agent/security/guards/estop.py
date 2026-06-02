"""Emergency Stop (E-Stop) — global kill switch for all tool execution.

Provides a fail-closed emergency brake that can freeze all tool calls
or terminate all running agents. State is persisted to a JSON file so
it survives process restarts.

[INPUT]
- (none — self-contained, pure standard library + json)

[OUTPUT]
- EStopLevel: ToolFreeze / KillAll
- EStopState: current state snapshot (frozen dataclass)
- EStopGuard: global singleton managing the stop state
- check_estop(): fast-path check for middleware integration

[POS]
Global guard. Checked as the very first step in tool_interceptor_middleware.
When activated, all tool calls are rejected until explicitly resumed.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)


class EStopLevel(StrEnum):
    """Severity level of the emergency stop."""

    NONE = "none"
    TOOL_FREEZE = "tool_freeze"
    KILL_ALL = "kill_all"


@dataclass(frozen=True, slots=True)
class EStopState:
    """Immutable snapshot of the current E-Stop state."""

    level: EStopLevel
    reason: str
    activated_at: float
    activated_by: str

    def is_active(self) -> bool:
        return self.level != EStopLevel.NONE


_INACTIVE = EStopState(level=EStopLevel.NONE, reason="", activated_at=0.0, activated_by="")


class EStopGuard:
    """Global emergency stop guard with JSON persistence.

    Thread-safe. Uses atomic write (write-to-temp + rename) for
    crash-safe persistence. Fail-closed: if the state file cannot
    be read, all tool calls are rejected.
    """

    def __init__(self, state_path: Path | None = None) -> None:
        self._lock = Lock()
        self._state_path = state_path or self._default_path()
        self._cached: EStopState = _INACTIVE
        self._load()

    @staticmethod
    def _default_path() -> Path:
        return Path(".") / ".estop_state.json"

    def _load(self) -> None:
        """Load persisted state. Fail-closed on any error."""
        try:
            if self._state_path.exists():
                raw = json.loads(self._state_path.read_text(encoding="utf-8"))
                self._cached = EStopState(
                    level=EStopLevel(raw["level"]),
                    reason=raw.get("reason", ""),
                    activated_at=raw.get("activated_at", 0.0),
                    activated_by=raw.get("activated_by", ""),
                )
            else:
                self._cached = _INACTIVE
        except Exception:
            logger.error("Failed to read E-Stop state — fail-closed: rejecting all tool calls")
            self._cached = EStopState(
                level=EStopLevel.KILL_ALL,
                reason="E-Stop state file corrupted or unreadable (fail-closed)",
                activated_at=time.time(),
                activated_by="system",
            )

    def _persist(self, state: EStopState) -> None:
        """Persist E-Stop state atomically."""
        from myrm_agent_harness.infra.atomic_write import atomic_write

        try:
            atomic_write(self._state_path, json.dumps(asdict(state), ensure_ascii=False))
        except Exception:
            logger.error("Failed to persist E-Stop state")

    @property
    def state(self) -> EStopState:
        return self._cached

    def activate(self, level: EStopLevel, reason: str, activated_by: str = "operator") -> EStopState:
        """Activate emergency stop at the given level."""
        if level == EStopLevel.NONE:
            raise ValueError("Use resume() to deactivate E-Stop")
        with self._lock:
            new_state = EStopState(level=level, reason=reason, activated_at=time.time(), activated_by=activated_by)
            self._cached = new_state
            self._persist(new_state)
            logger.warning("E-Stop activated: level=%s reason=%s by=%s", level, reason, activated_by)
            return new_state

    def resume(self, resumed_by: str = "operator") -> EStopState:
        """Explicitly deactivate emergency stop."""
        with self._lock:
            prev = self._cached
            self._cached = _INACTIVE
            self._persist(_INACTIVE)
            logger.warning("E-Stop resumed: prev_level=%s by=%s", prev.level, resumed_by)
            return _INACTIVE


_global_guard: EStopGuard | None = None
_init_lock = Lock()


def get_estop_guard(state_path: Path | None = None) -> EStopGuard:
    """Get or create the global EStopGuard singleton."""
    global _global_guard
    if _global_guard is None:
        with _init_lock:
            if _global_guard is None:
                _global_guard = EStopGuard(state_path)
    return _global_guard


def check_estop() -> EStopState | None:
    """Fast-path check for middleware integration.

    Returns the active EStopState if emergency stop is engaged,
    or None if everything is normal.
    """
    guard = get_estop_guard()
    state = guard.state
    if state.is_active():
        return state
    return None

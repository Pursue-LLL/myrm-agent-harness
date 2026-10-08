"""Type definitions for Computer-Use Safe Enclave and Action Replay Audit Deck.

[INPUT]
None.

[OUTPUT]
- DesktopActionType, DesktopActionRiskLevel
- CriticalDesktopAction, ActionEnclaveChallenge, DesktopActionAuditRecord
- DesktopActionPanickedError, CriticalActionBlockedError

[POS]
Harness core security subsystem for computer-use desktop control,
enforcing pre-action interception of high-risk clicks/keystrokes and emergency stop.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class DesktopActionType(StrEnum):
    """Types of OS-level desktop actions dispatched by computer-use agents."""

    MOUSE_CLICK = "mouse_click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    KEY_PRESS = "key_press"
    TEXT_INPUT = "text_input"
    DRAG_AND_DROP = "drag_and_drop"
    SYSTEM_COMMAND = "system_command"


class DesktopActionRiskLevel(StrEnum):
    """Assessed risk tier of candidate desktop action."""

    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class CriticalDesktopAction:
    """Detailed parameters and semantic intent of an impending desktop action."""

    action_id: str
    action_type: DesktopActionType
    semantic_intent: str
    coordinates: tuple[int, int] | None = None
    target_element_text: str | None = None
    payload_text: str | None = None
    risk_level: DesktopActionRiskLevel = DesktopActionRiskLevel.SAFE
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class ActionEnclaveChallenge:
    """Interception challenge issued before dispatching a critical desktop action."""

    challenge_id: str
    action: CriticalDesktopAction
    reason: str
    status: str  # pending, approved, rejected, panicked
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class DesktopActionAuditRecord:
    """Telemetry record persisted for live intent HUD display and action replay."""

    record_id: str
    action: CriticalDesktopAction
    enclave_verified: bool
    executed: bool
    execution_latency_ms: float
    status: str
    recorded_at: float = field(default_factory=time.time)


class DesktopActionPanickedError(Exception):
    """Raised when an operation is aborted due to emergency panic stop trigger."""

    def __init__(self, reason: str = "Emergency panic stop activated") -> None:
        super().__init__(f"Desktop Agent Emergency Panic: {reason}")
        self.reason = reason


class CriticalActionBlockedError(Exception):
    """Raised when a critical desktop action is denied by the user or security policy."""

    def __init__(self, action_id: str, reason: str) -> None:
        super().__init__(f"Desktop action '{action_id}' blocked: {reason}")
        self.action_id = action_id
        self.reason = reason

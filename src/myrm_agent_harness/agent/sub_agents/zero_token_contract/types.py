"""Zero-Token Visualization Contract types and data definitions.

Hermes3D and Fleet Canvas deterministic runtime event projection without token burning.

[INPUT]
- __future__
- time
- dataclasses
- typing

[OUTPUT]
- ZeroTokenEventSource
- ZeroTokenEventType
- ProtectedVizSurface
- PROTECTED_VIZ_SURFACES
- ZeroTokenContractViolationError
- ZeroTokenEvent
- VizCallAuditRecord
- ZeroTokenAuditSnapshot

[POS]
Zero-Token Visualization Contract types and data definitions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

ZeroTokenEventSource = Literal[
    "runtime_sse",
    "gateway_webhook",
    "liveness_heartbeat",
    "kanban_webhook",
]

ZeroTokenEventType = Literal[
    "subagent_spawned",
    "subagent_status_update",
    "subagent_terminated",
    "tool_start",
    "tool_finish",
    "node_heartbeat",
    "kanban_transition",
]

ProtectedVizSurface = Literal[
    "fleet_canvas",
    "3d_office",
    "pet_status",
    "ambient_display",
    "active_now_badge",
]

PROTECTED_VIZ_SURFACES: frozenset[str] = frozenset({
    "fleet_canvas",
    "3d_office",
    "pet_status",
    "ambient_display",
    "active_now_badge",
    "viz",
    "canvas",
    "office_3d",
    "pet_animation",
})


class ZeroTokenContractViolationError(RuntimeError):
    """Raised when a visualization surface attempts to invoke LLM APIs, violating the contract."""

    def __init__(self, surface: str, reason: str) -> None:
        super().__init__(f"ZeroTokenContractViolation on surface '{surface}': {reason}")
        self.surface = surface
        self.reason = reason


@dataclass(frozen=True)
class ZeroTokenEvent:
    """Deterministic runtime event emitted by runtime without LLM involvement."""

    event_id: str
    source: ZeroTokenEventSource
    event_type: ZeroTokenEventType
    agent_id: str
    payload: dict[str, str | int | float | bool]
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class VizCallAuditRecord:
    """Audit record capturing an intercepted or evaluated LLM invocation attempt."""

    caller_surface: str
    prompt_chars: int
    is_violation: bool
    intercepted_reason: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ZeroTokenAuditSnapshot:
    """Audit summary proving zero tokens spent by the visualization layer."""

    chat_id: str
    total_events_mirrored: int = 0
    total_tokens_spent: int = 0  # Contract strictly enforces 0
    saved_tokens_estimated: int = 0
    violations_intercepted: int = 0
    is_compliant: bool = True
    recent_violations: list[VizCallAuditRecord] = field(default_factory=list)
    last_mirrored_at: float | None = None

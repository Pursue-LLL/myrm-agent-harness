"""Domain contracts and data types for interactive clarify cards lifecycle.

[INPUT]
- None (Self-contained strongly-typed contracts).

[OUTPUT]
- ClarifyCardStatus: Lifecycle status of a clarify card (pending, answered, expired, invalidated).
- ClarifyResponsePath: UI presentation and delivery path (dashboard, inline, modal).
- ClarifyOptionItem: Discrete selectable choice for a clarification question.
- ClarifyCardPayload: Immutable record representing a clarification card.
- ClarifyDispatchReceipt: Cryptographically verifiable receipt for clarification lifecycle events.

[POS]
Domain contracts and data models for session clarification cards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import time
from typing import Mapping


class ClarifyCardStatus(str, Enum):
    """Lifecycle status states for clarification cards."""

    PENDING = "pending"
    ANSWERED = "answered"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


class ClarifyResponsePath(str, Enum):
    """Delivery routing channel for clarification UI cards."""

    DASHBOARD = "dashboard"
    INLINE = "inline"
    MODAL = "modal"


@dataclass(frozen=True)
class ClarifyOptionItem:
    """Discrete selectable choice provided in a clarification card."""

    label: str
    value: str
    description: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "label": self.label,
            "value": self.value,
            "description": self.description,
        }


@dataclass(frozen=True)
class ClarifyCardPayload:
    """Canonical clarification card model capturing questions, choices, answers, and states."""

    request_id: str
    session_id: str
    connection_id: str
    question: str
    options: tuple[ClarifyOptionItem, ...] = ()
    allow_custom_input: bool = True
    timeout_seconds: float = 300.0
    response_path: ClarifyResponsePath = ClarifyResponsePath.DASHBOARD
    status: ClarifyCardStatus = ClarifyCardStatus.PENDING
    user_answer: str | None = None
    created_at: float = field(default_factory=time.time)
    resolved_at: float | None = None
    metadata: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)

    @property
    def is_active_pending(self) -> bool:
        """Indicates whether this card is currently pending user input."""
        return self.status == ClarifyCardStatus.PENDING

    @property
    def is_timed_out(self) -> bool:
        """Determines if the card has passed its timeout duration."""
        if not self.is_active_pending:
            return False
        return (time.time() - self.created_at) > self.timeout_seconds

    def to_dict(self) -> dict[str, str | int | float | bool | None | list[dict[str, str | None]] | dict[str, str | int | float | bool | None]]:
        """Normalize into a JSON-serializable dictionary."""
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "connection_id": self.connection_id,
            "question": self.question,
            "options": [opt.to_dict() for opt in self.options],
            "allow_custom_input": self.allow_custom_input,
            "timeout_seconds": self.timeout_seconds,
            "response_path": self.response_path.value,
            "status": self.status.value,
            "user_answer": self.user_answer,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ClarifyDispatchReceipt:
    """Verifiable receipt recording clarification card state transitions."""

    receipt_id: str
    request_id: str
    session_id: str
    action: str
    status: ClarifyCardStatus
    fingerprint: str
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        *,
        receipt_id: str,
        request_id: str,
        session_id: str,
        action: str,
        status: ClarifyCardStatus,
        card: ClarifyCardPayload,
    ) -> ClarifyDispatchReceipt:
        payload = {
            "receipt_id": receipt_id,
            "request_id": request_id,
            "session_id": session_id,
            "action": action,
            "status": status.value,
            "user_answer": card.user_answer,
            "created_at": card.created_at,
            "resolved_at": card.resolved_at,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        fp = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return cls(
            receipt_id=receipt_id,
            request_id=request_id,
            session_id=session_id,
            action=action,
            status=status,
            fingerprint=fp,
        )

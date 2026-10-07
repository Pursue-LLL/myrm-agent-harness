"""Strongly typed contracts for Continuable Cron Delivery and Session Mirroring Suite (Item 215).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- CronMirrorRoleMode: Ingestion role strategy ensuring LLM alternation safety.
- ContinuableJobSpec: Job configuration defining continuation and session attachment policy.
- CronDeliveryRecord: Execution payload record of a delivered cron brief.
- CronMirroringOutcome: Telemetry outcome of session mirroring and thread allocation.
- CronMirrorConfig: Tunable configurations for cron session mirroring and context formatting.

[POS]
- Eliminates fire-and-forget cron disconnect by mirroring delivered briefs into session histories
- as alternation-safe user turns and providing instant follow-up context in dedicated threads.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class CronMirrorRoleMode(str, enum.Enum):
    """Message role strategy used when mirroring a cron delivery into session context."""

    LABELLED_USER_TURN = "labelled_user_turn"
    SYSTEM_INSTRUCTION_FRAME = "system_instruction_frame"
    ASSISTANT_DELIVERY = "assistant_delivery"


@dataclass(frozen=True, slots=True)
class ContinuableJobSpec:
    """Strongly typed specification defining continuation capabilities of a scheduled cron job."""

    job_id: str
    job_name: str
    continuable: bool = True
    attach_to_session: bool = True
    prefer_isolated_thread: bool = False

    def to_dict(self) -> dict[str, object]:
        """Serializes job spec to dictionary."""
        return {
            "job_id": self.job_id,
            "job_name": self.job_name,
            "continuable": self.continuable,
            "attach_to_session": self.attach_to_session,
            "prefer_isolated_thread": self.prefer_isolated_thread,
        }


@dataclass(frozen=True, slots=True)
class CronDeliveryRecord:
    """Persisted delivery payload record of a triggered cron job run."""

    delivery_id: str
    job_id: str
    job_name: str
    target_session_id: str
    content: str
    delivered_at: float = field(default_factory=time.time)
    thread_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serializes delivery record to dictionary."""
        return {
            "delivery_id": self.delivery_id,
            "job_id": self.job_id,
            "job_name": self.job_name,
            "target_session_id": self.target_session_id,
            "content": self.content,
            "delivered_at": self.delivered_at,
            "thread_id": self.thread_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class CronMirroringOutcome:
    """Telemetry report recording the result of mirroring a cron brief into conversation history."""

    mirrored: bool
    target_session_id: str
    delivery_id: str
    injected_role: str
    injected_content_preview: str
    thread_id: str | None
    alternation_safe: bool
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Serializes mirroring outcome to dictionary."""
        return {
            "mirrored": self.mirrored,
            "target_session_id": self.target_session_id,
            "delivery_id": self.delivery_id,
            "injected_role": self.injected_role,
            "injected_content_preview": self.injected_content_preview,
            "thread_id": self.thread_id,
            "alternation_safe": self.alternation_safe,
            "duration_ms": self.duration_ms,
        }


@dataclass(slots=True)
class CronMirrorConfig:
    """Configuration governing cron message mirroring, formatting, and safety floors."""

    enabled: bool = True
    default_role_mode: CronMirrorRoleMode = CronMirrorRoleMode.LABELLED_USER_TURN
    max_delivery_chars_in_context: int = 12000
    tag_template: str = "[Cron Delivery Brief: {job_name} | {timestamp}]"

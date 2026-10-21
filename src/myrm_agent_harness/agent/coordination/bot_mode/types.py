"""Strongly-typed DTOs and Enums for Bot Mode Named Profile Roster & Inter-Bot Mailbox (Item 33).

Defines the contracts for named AI colleague profiles ("workstations"),
inter-bot asynchronous direct messaging, and @mention task dispatching.

[INPUT]
- __future__
- dataclasses
- datetime
- enum

[OUTPUT]
- ScalarValue
- BotStatus
- MessagePriority
- BotProfile
- BotMessage
- MentionDispatchResult

[POS]
Strongly-typed DTOs and Enums for Bot Mode Named Profile Roster & Inter-Bot Mailbox (Item 33).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

ScalarValue = str | int | float | bool | None


class BotStatus(StrEnum):
    """Execution availability state of a named bot workstation."""

    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"


class MessagePriority(StrEnum):
    """Urgency level for inter-bot mailbox delivery."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass(frozen=True)
class BotProfile:
    """A distinct named AI colleague workstation with dedicated identity and role specialization."""

    bot_id: str
    handle: str
    display_name: str
    role_description: str
    avatar_seed: str
    model_tier: str
    skills: tuple[str, ...] = field(default_factory=tuple)
    tools: tuple[str, ...] = field(default_factory=tuple)
    status: BotStatus = BotStatus.IDLE
    active_task_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def __post_init__(self) -> None:
        # Normalize handle to lowercase with leading '@'
        norm_handle = self.handle.strip().lower()
        if not norm_handle.startswith("@"):
            norm_handle = f"@{norm_handle}"
        object.__setattr__(self, "handle", norm_handle)


@dataclass(frozen=True)
class BotMessage:
    """A structured asynchronous message or delegated work item delivered to a bot's mailbox."""

    message_id: str
    from_bot: str
    to_bot: str
    thread_id: str
    subject: str
    body: str
    priority: MessagePriority = MessagePriority.NORMAL
    task_payload: dict[str, ScalarValue] = field(default_factory=dict)
    is_read: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class MentionDispatchResult:
    """Report on resolving and delivering a parsed @mention reference to a target bot."""

    dispatched: bool
    target_bot_id: str | None
    target_handle: str | None
    message_id: str | None
    note: str

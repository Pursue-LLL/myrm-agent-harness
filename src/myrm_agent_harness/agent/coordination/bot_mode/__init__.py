"""Bot Mode Named Profile Roster & Inter-Bot Mailbox package (Item 33)."""

from .mailbox_relay import InterBotMailboxRelay
from .roster import NamedBotRoster
from .types import (
    BotMessage,
    BotProfile,
    BotStatus,
    MentionDispatchResult,
    MessagePriority,
    ScalarValue,
)

__all__ = [
    "BotMessage",
    "BotProfile",
    "BotStatus",
    "InterBotMailboxRelay",
    "MentionDispatchResult",
    "MessagePriority",
    "NamedBotRoster",
    "ScalarValue",
]

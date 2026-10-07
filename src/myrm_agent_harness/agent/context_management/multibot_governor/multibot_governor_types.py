"""Type definitions for Multi-Bot Shared Group Chatter Governor.

Provides immutable data contracts for continuous bot turn tracking,
incremental cognitive value evaluation, turn mutex tokens, and circuit-breaker decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time


class GovernorAction(StrEnum):
    """Action dictated by the multi-bot chatter governor."""

    ALLOW = "allow"
    PASS = "pass"
    CIRCUIT_BREAK = "circuit_break"
    EMERGENCY_STOP = "emergency_stop"


class MessageSenderRole(StrEnum):
    """Role classification of message senders in a group chat."""

    USER = "user"
    BOT = "bot"
    SYSTEM = "system"


@dataclass(frozen=True)
class MultiBotGovernorConfig:
    """Configuration governing multi-bot shared group chat interaction safety."""

    max_continuous_bot_turns: int = 2
    mutex_lease_seconds: float = 30.0
    enable_incremental_value_gate: bool = True
    circuit_break_notice_template: str = (
        "🤖 已完成 {turns} 轮 AI 自主协作接力，为避免重复消耗算力已暂停，等待您的进一步指令"
    )


@dataclass(frozen=True)
class BotTurnEvent:
    """Represents a discrete turn event submitted to the governor."""

    sender_id: str
    sender_role: MessageSenderRole
    content: str
    target_bot_id: str | None = None
    mentioned_bot_ids: tuple[str, ...] = field(default_factory=tuple)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class CognitiveValueEvaluation:
    """Result of pre-flight incremental cognitive value introspection."""

    should_respond: bool
    is_explicitly_mentioned: bool
    has_substantive_increment: bool
    reason: str
    action: GovernorAction


@dataclass(frozen=True)
class MutexAcquireResult:
    """Result of attempting to acquire the group turn mutex token."""

    acquired: bool
    holder_bot_id: str | None
    token_id: str | None
    expires_at: float | None
    reason: str


@dataclass(frozen=True)
class GovernorDecision:
    """Comprehensive decision emitted before a bot attempts to speak."""

    action: GovernorAction
    should_respond: bool
    continuous_bot_turns: int
    reason: str
    notice_message: str | None = None
    mutex_token_id: str | None = None

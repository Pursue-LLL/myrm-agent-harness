"""Types and data contracts for sliding window session lifecycle and KV cache keeper."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SessionLifecycleState(StrEnum):
    """Lifecycle states of a session governed by sliding inactivity window."""

    ACTIVE = "active"
    IDLE_STABLE = "idle_stable"
    EXPIRED_PENDING_ARCHIVE = "expired_pending_archive"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class InactivityWindowConfig:
    """Configuration for inactivity sliding window and KV cache retention."""

    inactivity_timeout_seconds: float = 72.0 * 3600.0  # Default 72 hours
    idle_warning_threshold_seconds: float = 48.0 * 3600.0  # 48 hours idle notice
    enable_prefix_caching_guard: bool = True
    auto_crystallize_on_archive: bool = True


@dataclass(frozen=True)
class PrefixCacheFingerprint:
    """Stable fingerprint of system prompt and static tools context for KV cache."""

    prefix_hash: str
    token_count: int
    last_verified_at: float
    is_frozen: bool = True


@dataclass(frozen=True)
class CrystallizedSessionMemory:
    """Crystallized long-term memory payload generated upon session archival."""

    session_id: str
    crystallized_at: float
    inactivity_duration_seconds: float
    extracted_facts: tuple[str, ...] = field(default_factory=tuple)
    key_decisions: tuple[str, ...] = field(default_factory=tuple)
    user_preferences: tuple[str, ...] = field(default_factory=tuple)
    summary_headline: str = ""


@dataclass(frozen=True)
class SessionLifecycleSnapshot:
    """Immutable snapshot of the session state, activity timeline, and cache status."""

    session_id: str
    state: SessionLifecycleState
    created_at: float
    last_active_at: float
    inactivity_seconds: float
    message_count: int
    cache_fingerprint: PrefixCacheFingerprint | None = None
    crystallized_memory: CrystallizedSessionMemory | None = None

"""Type definitions for Channel Thread to Session Dynamic Binding and Isolated Branching.

Provides immutable data contracts for thread-aware channel routing keys, isolated
child session branching, concurrency policy, and thread archive handoff summaries.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ThreadBindingKey: Canonical identifier uniquely binding a channel, chat, and thread tuple.
- ThreadIsolationPolicy: Governing policy for channel thread session branching and lifecycle.
- ThreadSessionBranch: An isolated conversation branch dedicated to a specific channel thread.
- ThreadRoutingDecision: Routing outcome determining target isolated session and outbound thread bindings.

[POS]
Type definitions for Channel Thread to Session Dynamic Binding and Isolated Branching.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ThreadBindingKey:
    """Canonical identifier uniquely binding a channel, chat, and thread tuple."""

    channel: str
    chat_id: str
    thread_id: str | None
    canonical_session_key: str


@dataclass(frozen=True)
class ThreadIsolationPolicy:
    """Governing policy for channel thread session branching and lifecycle."""

    inherit_main_context_on_spawn: bool = False
    enable_thread_lock_concurrency: bool = True
    auto_summarize_on_archive: bool = True


@dataclass(frozen=True)
class ThreadSessionBranch:
    """An isolated conversation branch dedicated to a specific channel thread."""

    branch_id: str
    session_key: str
    channel: str
    chat_id: str
    thread_id: str
    created_at: float
    message_count: int
    is_active: bool
    summary: str | None = None


@dataclass(frozen=True)
class ThreadRoutingDecision:
    """Routing outcome determining target isolated session and outbound thread bindings."""

    target_session_key: str
    is_thread_isolated: bool
    branch_id: str
    reply_to_thread_id: str | None

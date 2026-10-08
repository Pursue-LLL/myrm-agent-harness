# [INPUT]: None
# [OUTPUT]: CachePartitionedContextBundle, DormantSnapshot, EventAuditRecord, EventEnvelopePayload, EventSourceTier, HydrationState
# [POS]: agent/context_management/event_cache_preservation/event_envelope_types.py

"""Domain models and contracts for cache-preserving event envelope and cold-start hydration suite.

[INPUT]
- None (Self-contained domain models).

[OUTPUT]
- EventSourceTier: Origin tier of asynchronous push events (MCP push, webhook, manual, cron).
- EventEnvelopePayload: Structured payload encapsulated into an ephemeral event frame.
- CachePartitionedContextBundle: 2-tier context separating static prefix from ephemeral event frame.
- DormantSnapshot: Serialized hibernation state (<10MB) for frozen sandboxes.
- HydrationState: Lifecycle states (ACTIVE_RUNNING, DORMANT_SLEEP, HYDRATING).
- EventAuditRecord: Separate audit trail preventing high-volume events from polluting chat windows.

[POS]
Domain contracts for Item 316 CachePreservingEventEnvelopeAndColdStartHydrationSuite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class EventSourceTier(str, Enum):
    """Origin category of incoming asynchronous events."""

    MCP_PUSH_EVENT = "mcp_push"       # External MCP server push notification
    WEBHOOK_SYSTEM = "webhook_system" # External enterprise webhook payload
    USER_MANUAL = "user_manual"       # Out-of-band human steering
    TIMER_CRON = "timer_cron"         # Background cron tick or scheduled alarm


class HydrationState(str, Enum):
    """Sandbox lifecycle hibernation and wake state machine."""

    ACTIVE_RUNNING = "active_running"
    DORMANT_SLEEP = "dormant_sleep"
    HYDRATING = "hydrating"


@dataclass(frozen=True)
class EventEnvelopePayload:
    """Isolated dynamic event frame appended strictly at the tail of messages."""

    event_id: str
    source: EventSourceTier
    timestamp_iso: str
    priority: str                     # "critical", "high", "normal", "low"
    payload_text: str

    def format_tail_xml_frame(self) -> str:
        """Format event payload into an immutable XML trigger block."""
        return (
            f'<event_trigger id="{self.event_id}" source="{self.source.value}" '
            f'timestamp="{self.timestamp_iso}" priority="{self.priority}">\n'
            f"{self.payload_text}\n"
            f"</event_trigger>"
        )


@dataclass(frozen=True)
class CachePartitionedContextBundle:
    """Dual-tier context protecting prefix cache while delivering real-time event updates."""

    static_prefix_tier: str
    conversation_history_tier: Sequence[str]
    ephemeral_event_frame: str
    prefix_tokens_estimate: int
    event_tokens_estimate: int
    cache_hit_ratio_projected: float

    def render_full_prompt(self) -> str:
        """Assemble the complete context sequence while keeping static prefix at byte 0."""
        parts: list[str] = [self.static_prefix_tier]
        if self.conversation_history_tier:
            parts.extend(self.conversation_history_tier)
        if self.ephemeral_event_frame:
            parts.append(self.ephemeral_event_frame)
        return "\n\n".join(p for p in parts if p.strip()).strip()


@dataclass(frozen=True)
class DormantSnapshot:
    """Lightweight (<10MB) state snapshot for hibernating sandboxes during inactive windows."""

    session_id: str
    last_active_timestamp: str
    serialized_state_bytes: int
    snapshot_hash: str
    cached_prefix_text: str = ""
    history_turns_count: int = 0


@dataclass(frozen=True)
class EventAuditRecord:
    """Audit log decoupled from user-facing conversation window."""

    audit_id: str
    event_id: str
    source: EventSourceTier
    timestamp_iso: str
    summary: str
    was_promoted_to_user: bool = False
    details_dump: str = ""

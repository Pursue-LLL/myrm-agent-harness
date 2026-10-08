"""Types and data structures for persistent session pinning and cross-platform deeplinking.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- SessionPinState: Data model representing persistent session pin status and ordering.
- SessionDeeplinkRoute: Resolved deeplink route for instant navigation to pinned sessions.
- SessionPinSyncReceipt: Auditable cryptographic receipt certifying pin mutations and sync.

[POS]
Types and data structures for persistent session pinning and cross-platform deeplinking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class PinActionKind(str, Enum):
    """Classification of session pin mutation operations."""

    PIN = "pin"
    UNPIN = "unpin"
    REORDER = "reorder"


@dataclass(frozen=True)
class SessionPinState:
    """Persistent pin metadata stored with session entity."""

    session_id: str
    is_pinned: bool
    pinned_at_iso: Optional[str] = None
    pin_order: int = 0
    pin_label: str = ""


@dataclass(frozen=True)
class SessionDeeplinkRoute:
    """Resolved deep link URI for instant navigation to session or entry."""

    deeplink_url: str
    session_id: str
    target_entry_id: Optional[str] = None
    route_path: str = ""


@dataclass(frozen=True)
class SessionPinSyncReceipt:
    """Receipt documenting session pin modification and multi-client synchronization."""

    receipt_id: str
    session_id: str
    action: PinActionKind
    is_pinned: bool
    total_pinned_sessions_count: int
    sync_hash: str
    synced_at_iso: str

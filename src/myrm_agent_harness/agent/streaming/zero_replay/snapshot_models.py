"""[INPUT]
- None (pure data model)

[OUTPUT]
- SessionAtomicSnapshot: Immutable atomic state snapshot contract
- LiveStreamFilterConfig: Gateway filter config for live-only event subscriptions

[POS]
Harness framework layer contracts for Zero-Replay reconnect protocol (inspired by earendil-works/pi harness-v2 UI model).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

SessionLifecycleStatus = Literal["idle", "running", "paused", "interrupted", "error"]


@dataclass(slots=True)
class SessionAtomicSnapshot:
    session_id: str
    epoch_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state_version: int = 1
    snapshot_timestamp_ms: float = field(default_factory=lambda: time.time() * 1000.0)
    status: SessionLifecycleStatus = "idle"
    leaf_entry_id: str | None = None
    active_tool_calls: list[dict[str, str]] = field(default_factory=list)
    message_count: int = 0
    latest_turn_summary: str | None = None
    artifacts_summary: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class LiveStreamFilterConfig:
    client_snapshot_timestamp_ms: float
    client_state_version: int
    allow_equal_timestamp: bool = False

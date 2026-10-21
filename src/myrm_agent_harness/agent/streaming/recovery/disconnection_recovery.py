"""Resilient disconnection recovery manager with offline action staging.

Orchestrates connection lifecycle transitions, client catch-up handshakes,
heartbeat health monitoring, and off-line action queueing to eliminate
dead pages and lost commands during network handovers or screen lockouts.

[OUTPUT]
- ResilientDisconnectionRecoveryManager: Connection coordinator with staged actions.

[INPUT]
- __future__
- asyncio
- time
- uuid

[OUTPUT]
- ResilientDisconnectionRecoveryManager

[POS]
Resilient disconnection recovery manager with offline action staging.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from myrm_agent_harness.agent.streaming.recovery.recovery_types import (
    ConnectionState,
    ReplayBatch,
    StagedAction,
)
from myrm_agent_harness.agent.streaming.recovery.replay_buffer import (
    CircularEventReplayBuffer,
)

_MAX_STAGED_ACTIONS: int = 100


class ResilientDisconnectionRecoveryManager:
    """Coordinates stream disconnection recovery, handshake catch-up, and action queueing."""

    def __init__(
        self,
        stream_id: str,
        replay_buffer: CircularEventReplayBuffer | None = None,
        *,
        max_staged_actions: int = _MAX_STAGED_ACTIONS,
    ) -> None:
        self.stream_id: str = stream_id
        self.replay_buffer: CircularEventReplayBuffer = (
            replay_buffer or CircularEventReplayBuffer(stream_id)
        )
        self.max_staged_actions: int = max(1, max_staged_actions)

        self._state: ConnectionState = "CONNECTED"
        self._last_heartbeat_ts: float = time.time()
        self._disconnected_at: float | None = None
        self._staged_actions: list[StagedAction] = []
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def state(self) -> ConnectionState:
        """Return current connection lifecycle state."""
        return self._state

    @property
    def staged_actions_count(self) -> int:
        """Return number of enqueued offline actions waiting to be flushed."""
        return len(self._staged_actions)

    @property
    def disconnected_duration(self) -> float:
        """Return seconds since disconnection, or 0.0 if connected."""
        if self._state == "CONNECTED" or self._disconnected_at is None:
            return 0.0
        return max(0.0, time.time() - self._disconnected_at)

    async def record_heartbeat(self) -> None:
        """Record an inbound heartbeat/ping from the client."""
        async with self._lock:
            self._last_heartbeat_ts = time.time()
            if self._state == "DISCONNECTED" or self._state == "RECONNECTING":
                self._state = "CONNECTED"
                self._disconnected_at = None

    async def mark_connected(self) -> None:
        """Explicitly transition to CONNECTED state."""
        async with self._lock:
            self._state = "CONNECTED"
            self._disconnected_at = None
            self._last_heartbeat_ts = time.time()

    async def mark_disconnected(self, reason: str | None = None) -> None:
        """Mark connection as DISCONNECTED and timestamp dropout moment."""
        async with self._lock:
            if self._state != "CLOSED":
                self._state = "DISCONNECTED"
                self._disconnected_at = time.time()

    async def mark_reconnecting(self) -> None:
        """Mark client reconnection attempt in progress."""
        async with self._lock:
            if self._state != "CLOSED":
                self._state = "RECONNECTING"

    async def mark_resync_required(self) -> None:
        """Mark connection as requiring full state reconstruction."""
        async with self._lock:
            self._state = "RESYNC_REQUIRED"

    async def close(self) -> None:
        """Terminate connection and underlying replay buffer."""
        async with self._lock:
            self._state = "CLOSED"
            await self.replay_buffer.end_stream()

    async def check_heartbeat_timeout(self, timeout_seconds: float = 30.0) -> bool:
        """Evaluate if connection has gone silent beyond timeout threshold."""
        async with self._lock:
            if self._state == "CONNECTED":
                elapsed = time.time() - self._last_heartbeat_ts
                if elapsed > timeout_seconds:
                    self._state = "DISCONNECTED"
                    self._disconnected_at = time.time()
                    return True
            return False

    async def handle_reconnect(
        self, client_last_seq: int
    ) -> tuple[ConnectionState, ReplayBatch]:
        """Perform two-phase handshake replay query for reconnecting client."""
        async with self._lock:
            replay_batch = await self.replay_buffer.replay_since(client_last_seq)

            if replay_batch.status == "GAP_DETECTED":
                self._state = "RESYNC_REQUIRED"
            else:
                self._state = "CONNECTED"
                self._disconnected_at = None
                self._last_heartbeat_ts = time.time()

            return self._state, replay_batch

    async def stage_offline_action(
        self,
        action_type: str,
        payload: dict[str, object],
        *,
        action_id: str | None = None,
    ) -> StagedAction:
        """Enqueue user action triggered while network is offline."""
        aid = action_id or str(uuid.uuid4())
        action = StagedAction(
            action_id=aid,
            action_type=action_type,
            stream_id=self.stream_id,
            payload=payload,
            staged_at=time.time(),
        )

        async with self._lock:
            if len(self._staged_actions) >= self.max_staged_actions:
                # Evict oldest uncommitted action to enforce memory bounds
                self._staged_actions.pop(0)

            self._staged_actions.append(action)
            return action

    async def flush_staged_actions(self) -> list[StagedAction]:
        """Atomically drain and return all staged offline actions in order."""
        async with self._lock:
            actions = list(self._staged_actions)
            self._staged_actions.clear()
            return actions

"""Virtual Co-Dev Room orchestrator coordinating participants, VFS locks, and relays (Item 59).

[INPUT]
- Room creation, join/leave lifecycle events, service port relay registrations,
  and collaborative audit logs.

[OUTPUT]
- Synchronized VirtualRoomState snapshot unifying active participants, active VFS locks,
  borrowing grants, and live preview service endpoints.

[POS]
- Tutti-style high-level virtual workspace room coordinator for multi-human multi-agent co-dev.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence

from myrm_agent_harness.agent.sub_agents.virtual_room.agent_borrowing_gateway import (
    ZeroCredentialBorrowingGateway,
)
from myrm_agent_harness.agent.sub_agents.virtual_room.fs_lock_engine import (
    VirtualFilesystemLockEngine,
)
from myrm_agent_harness.agent.sub_agents.virtual_room.types import (
    ParticipantRoleEnum,
    RoomServicePortRelay,
    VirtualRoomActivityEvent,
    VirtualRoomParticipant,
    VirtualRoomState,
)


class VirtualCoDevRoomManager:
    """Coordinates collaborative virtual room sessions across humans and subagents."""

    def __init__(
        self,
        lock_ttl_seconds: float = 15.0,
        grant_ttl_seconds: float = 3600.0,
    ) -> None:
        self._lock_engine = VirtualFilesystemLockEngine(default_ttl_seconds=lock_ttl_seconds)
        self._borrowing_gateway = ZeroCredentialBorrowingGateway(
            default_grant_ttl_seconds=grant_ttl_seconds
        )
        self._rooms: dict[str, dict[str, str | float]] = {}
        self._participants: dict[str, dict[str, VirtualRoomParticipant]] = {}
        self._service_relays: dict[str, list[RoomServicePortRelay]] = {}
        self._activity_events: dict[str, list[VirtualRoomActivityEvent]] = {}

    @property
    def lock_engine(self) -> VirtualFilesystemLockEngine:
        """Returns the underlying filesystem-level in-flight lock coordinator."""
        return self._lock_engine

    @property
    def borrowing_gateway(self) -> ZeroCredentialBorrowingGateway:
        """Returns the zero-credential cross-user agent capability gateway."""
        return self._borrowing_gateway

    def create_room(self, room_id: str, name: str) -> VirtualRoomState:
        """Initializes a new collaborative virtual room workspace."""
        if not room_id.strip():
            raise ValueError("Room ID cannot be empty.")
        if not name.strip():
            raise ValueError("Room name cannot be empty.")

        now = time.time()
        self._rooms[room_id] = {
            "room_id": room_id,
            "name": name,
            "created_at": now,
            "last_activity_at": now,
        }
        self._participants[room_id] = {}
        self._service_relays[room_id] = []
        self._activity_events[room_id] = []

        self.record_activity_event(
            room_id=room_id,
            actor_id="system",
            event_type="room_created",
            details={"name": name},
        )
        return self.get_room_state(room_id)

    def join_room(
        self,
        room_id: str,
        participant_id: str,
        name: str,
        role: ParticipantRoleEnum,
        local_identity_bound: bool = True,
    ) -> VirtualRoomParticipant:
        """Adds a human or AI agent participant to the collaborative room."""
        if room_id not in self._rooms:
            raise KeyError(f"Room '{room_id}' does not exist.")

        now = time.time()
        participant = VirtualRoomParticipant(
            participant_id=participant_id,
            name=name,
            role=role,
            local_identity_bound=local_identity_bound,
            is_active=True,
            joined_at=now,
        )
        self._participants[room_id][participant_id] = participant
        self._rooms[room_id]["last_activity_at"] = now

        self.record_activity_event(
            room_id=room_id,
            actor_id=participant_id,
            event_type="participant_joined",
            details={"name": name, "role": role.value, "local_identity": local_identity_bound},
        )
        return participant

    def leave_room(self, room_id: str, participant_id: str) -> bool:
        """Marks a participant as inactive within the room."""
        if room_id not in self._participants or participant_id not in self._participants[room_id]:
            return False

        current = self._participants[room_id][participant_id]
        updated = VirtualRoomParticipant(
            participant_id=current.participant_id,
            name=current.name,
            role=current.role,
            local_identity_bound=current.local_identity_bound,
            is_active=False,
            joined_at=current.joined_at,
        )
        self._participants[room_id][participant_id] = updated
        self._rooms[room_id]["last_activity_at"] = time.time()

        self.record_activity_event(
            room_id=room_id,
            actor_id=participant_id,
            event_type="participant_left",
            details={"name": current.name},
        )
        return True

    def register_service_relay(
        self,
        room_id: str,
        service_name: str,
        port: int,
        launched_by_id: str,
    ) -> RoomServicePortRelay:
        """Exposes an internal sandbox service port as a room-wide live preview URL."""
        if room_id not in self._rooms:
            raise KeyError(f"Room '{room_id}' does not exist.")
        if port <= 0 or port > 65535:
            raise ValueError(f"Invalid service port '{port}'.")

        now = time.time()
        relay_id = f"relay-{uuid.uuid4().hex[:8]}"
        live_preview_url = f"https://preview-{room_id[:8]}-{port}.internal.myrm.dev/{service_name}"

        relay = RoomServicePortRelay(
            relay_id=relay_id,
            room_id=room_id,
            service_name=service_name,
            port=port,
            live_preview_url=live_preview_url,
            launched_by_id=launched_by_id,
            is_healthy=True,
            created_at=now,
        )
        self._service_relays[room_id].append(relay)
        self._rooms[room_id]["last_activity_at"] = now

        self.record_activity_event(
            room_id=room_id,
            actor_id=launched_by_id,
            event_type="service_relay_registered",
            details={"service_name": service_name, "port": port, "url": live_preview_url},
        )
        return relay

    def record_activity_event(
        self,
        room_id: str,
        actor_id: str,
        event_type: str,
        details: Mapping[str, str | int | float | bool] | None = None,
    ) -> VirtualRoomActivityEvent:
        """Appends an event to the persistent room organization memory log."""
        now = time.time()
        event_id = f"evt-{uuid.uuid4().hex[:8]}"
        event = VirtualRoomActivityEvent(
            event_id=event_id,
            room_id=room_id,
            actor_id=actor_id,
            event_type=event_type,
            details=dict(details) if details is not None else {},
            timestamp=now,
        )
        if room_id in self._activity_events:
            self._activity_events[room_id].append(event)
        return event

    def list_activity_events(self, room_id: str) -> Sequence[VirtualRoomActivityEvent]:
        """Retrieves chronological activity audit log for a given room."""
        return tuple(self._activity_events.get(room_id, []))

    def get_room_state(self, room_id: str) -> VirtualRoomState:
        """Assembles the current unified snapshot state of a collaborative room."""
        if room_id not in self._rooms:
            raise KeyError(f"Room '{room_id}' not found.")

        meta = self._rooms[room_id]
        participants = tuple(self._participants.get(room_id, {}).values())
        active_locks = self._lock_engine.list_active_locks()
        grants = self._borrowing_gateway.list_grants(room_id=room_id)
        relays = tuple(self._service_relays.get(room_id, []))

        return VirtualRoomState(
            room_id=room_id,
            name=str(meta["name"]),
            participants=participants,
            active_locks=active_locks,
            borrowing_grants=grants,
            service_relays=relays,
            created_at=float(meta["created_at"]),
            last_activity_at=float(meta["last_activity_at"]),
        )

    def list_rooms(self) -> Sequence[VirtualRoomState]:
        """Returns snapshot states of all managed virtual rooms."""
        return tuple(self.get_room_state(r_id) for r_id in self._rooms)

    def clear(self) -> None:
        """Resets all room orchestrator state and sub-engines."""
        self._rooms.clear()
        self._participants.clear()
        self._service_relays.clear()
        self._activity_events.clear()
        self._lock_engine.clear()
        self._borrowing_gateway.clear()

"""Virtual Room collaborative workspace & filesystem co-dev package (Item 59).

[INPUT]
- types, fs_lock_engine, agent_borrowing_gateway, room_manager submodules.

[OUTPUT]
- Public exports for Tutti-style multi-human multi-agent real-time co-dev suite.

[POS]
- Framework-level package entrypoint for Item 59.
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.virtual_room.agent_borrowing_gateway import (
    ZeroCredentialBorrowingGateway,
)
from myrm_agent_harness.agent.sub_agents.virtual_room.fs_lock_engine import (
    VirtualFilesystemLockEngine,
)
from myrm_agent_harness.agent.sub_agents.virtual_room.room_manager import (
    VirtualCoDevRoomManager,
)
from myrm_agent_harness.agent.sub_agents.virtual_room.types import (
    AgentBorrowingGrant,
    BorrowingGrantStatusEnum,
    FileBlockLeaseLock,
    LockScopeEnum,
    ParticipantRoleEnum,
    RoomServicePortRelay,
    VirtualRoomActivityEvent,
    VirtualRoomParticipant,
    VirtualRoomState,
)

__all__ = [
    "AgentBorrowingGrant",
    "BorrowingGrantStatusEnum",
    "FileBlockLeaseLock",
    "LockScopeEnum",
    "ParticipantRoleEnum",
    "RoomServicePortRelay",
    "VirtualCoDevRoomManager",
    "VirtualFilesystemLockEngine",
    "VirtualRoomActivityEvent",
    "VirtualRoomParticipant",
    "VirtualRoomState",
    "ZeroCredentialBorrowingGateway",
]

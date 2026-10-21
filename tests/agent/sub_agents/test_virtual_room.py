"""Unit tests for Virtual Room Collaborative Workspace & Filesystem Co-Dev Engine (Item 59).

[INPUT]
- Harness virtual_room package classes:
  VirtualFilesystemLockEngine, ZeroCredentialBorrowingGateway, VirtualCoDevRoomManager.

[OUTPUT]
- Pytest verification for in-flight VFS block locks, overlap conflict detection,
  zero-credential agent borrowing delegation, TTL expiry, and room service port relays.

[POS]
- myrm-agent-harness/tests/agent/sub_agents/test_virtual_room.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.virtual_room import (
    BorrowingGrantStatusEnum,
    LockScopeEnum,
    ParticipantRoleEnum,
    VirtualCoDevRoomManager,
    VirtualFilesystemLockEngine,
    ZeroCredentialBorrowingGateway,
)


@pytest.fixture
def lock_engine() -> VirtualFilesystemLockEngine:
    """Provides a fresh VirtualFilesystemLockEngine instance."""
    return VirtualFilesystemLockEngine(default_ttl_seconds=10.0)


@pytest.fixture
def gateway() -> ZeroCredentialBorrowingGateway:
    """Provides a fresh ZeroCredentialBorrowingGateway instance."""
    return ZeroCredentialBorrowingGateway(default_grant_ttl_seconds=300.0)


@pytest.fixture
def room_manager() -> VirtualCoDevRoomManager:
    """Provides a fresh VirtualCoDevRoomManager instance."""
    mgr = VirtualCoDevRoomManager(lock_ttl_seconds=10.0, grant_ttl_seconds=300.0)
    mgr.clear()
    return mgr


# --- 1. Filesystem Lock Engine Tests ---


def test_lock_engine_acquire_and_release(lock_engine: VirtualFilesystemLockEngine) -> None:
    # 1. Acquire line-range lock
    lock = lock_engine.acquire_lock(
        file_path="src/components/Header.tsx",
        holder_id="dev-alice",
        holder_role=ParticipantRoleEnum.HUMAN_DEV,
        start_line=10,
        end_line=25,
        scope=LockScopeEnum.LINE_RANGE,
        ttl_seconds=20.0,
    )
    assert lock.lock_id.startswith("lock-")
    assert lock.file_path == "src/components/Header.tsx"
    assert lock.start_line == 10
    assert lock.end_line == 25
    assert lock_engine.is_write_allowed("src/components/Header.tsx", "dev-alice", 15, 20) is True

    # 2. Non-overlapping write from another agent should be allowed
    assert lock_engine.is_write_allowed("src/components/Header.tsx", "agent-bob", 30, 45) is True

    # 3. Overlapping write from another agent should be disallowed
    assert lock_engine.is_write_allowed("src/components/Header.tsx", "agent-bob", 20, 35) is False

    # 4. Release lock
    released = lock_engine.release_lock(lock.lock_id, "dev-alice")
    assert released is True
    # Now write should be allowed
    assert lock_engine.is_write_allowed("src/components/Header.tsx", "agent-bob", 20, 35) is True


def test_lock_engine_overlap_conflicts(lock_engine: VirtualFilesystemLockEngine) -> None:
    # Alice locks lines 50-80
    lock_engine.acquire_lock(
        file_path="server/app.py",
        holder_id="dev-alice",
        holder_role=ParticipantRoleEnum.HUMAN_DEV,
        start_line=50,
        end_line=80,
        scope=LockScopeEnum.LINE_RANGE,
    )

    # Bob attempts to acquire overlapping lines 70-100 -> Conflict
    with pytest.raises(ValueError, match="overlaps with existing lock"):
        lock_engine.acquire_lock(
            file_path="server/app.py",
            holder_id="agent-bob",
            holder_role=ParticipantRoleEnum.AGENT_WORKER,
            start_line=70,
            end_line=100,
            scope=LockScopeEnum.LINE_RANGE,
        )

    # Bob attempts to acquire full file lock while Alice holds line range -> Conflict
    with pytest.raises(ValueError, match="Cannot acquire full lock"):
        lock_engine.acquire_lock(
            file_path="server/app.py",
            holder_id="agent-bob",
            holder_role=ParticipantRoleEnum.AGENT_WORKER,
            scope=LockScopeEnum.FILE_FULL,
        )


def test_lock_engine_full_file_lock_blocks_all(lock_engine: VirtualFilesystemLockEngine) -> None:
    # Agent Charlie locks entire config file
    lock_engine.acquire_lock(
        file_path="config.json",
        holder_id="agent-charlie",
        holder_role=ParticipantRoleEnum.AGENT_ARCHITECT,
        scope=LockScopeEnum.FILE_FULL,
    )

    with pytest.raises(ValueError, match="fully locked by agent_architect"):
        lock_engine.acquire_lock(
            file_path="config.json",
            holder_id="dev-alice",
            holder_role=ParticipantRoleEnum.HUMAN_DEV,
            start_line=1,
            end_line=5,
            scope=LockScopeEnum.LINE_RANGE,
        )


def test_lock_engine_renew_and_unauthorized_release(
    lock_engine: VirtualFilesystemLockEngine,
) -> None:
    lock = lock_engine.acquire_lock(
        file_path="main.py",
        holder_id="dev-alice",
        holder_role=ParticipantRoleEnum.HUMAN_DEV,
        ttl_seconds=5.0,
    )

    # Renew lock
    renewed = lock_engine.renew_lock(lock.lock_id, "dev-alice", extension_seconds=30.0)
    assert renewed.expires_at > lock.expires_at

    # Unauthorized release attempt by Bob -> PermissionError
    with pytest.raises(PermissionError, match="not authorized to release lock"):
        lock_engine.release_lock(lock.lock_id, "agent-bob")


# --- 2. Zero-Credential Borrowing Gateway Tests ---


def test_zero_credential_borrowing_delegation_flow(
    gateway: ZeroCredentialBorrowingGateway,
) -> None:
    # Alice (has Claude 3.7 Pro) grants 1000 tokens to Bob
    grant = gateway.create_grant(
        room_id="room-alpha",
        owner_id="alice-pro",
        borrower_id="bob-free",
        target_agent_model="claude-3-7-sonnet",
        quota_tokens=1000,
        ttl_seconds=3600.0,
    )
    assert grant.grant_id.startswith("grant-")
    assert grant.status == BorrowingGrantStatusEnum.ACTIVE

    # Bob delegates execution
    ok, response, used = gateway.delegate_execution(
        grant_id=grant.grant_id,
        borrower_id="bob-free",
        prompt="Write a quicksort function in Rust",
        token_cost=300,
    )
    assert ok is True
    assert "quicksort" in response
    assert used == 300

    current = gateway.get_grant(grant.grant_id)
    assert current.used_tokens == 300
    assert current.status == BorrowingGrantStatusEnum.ACTIVE


def test_zero_credential_borrowing_quota_exhaustion_and_revocation(
    gateway: ZeroCredentialBorrowingGateway,
) -> None:
    grant = gateway.create_grant(
        room_id="room-beta",
        owner_id="alice",
        borrower_id="bob",
        target_agent_model="o3-mini",
        quota_tokens=500,
    )

    # Execute 400 tokens -> OK
    gateway.delegate_execution(grant.grant_id, "bob", "Task 1", token_cost=400)

    # Attempt 200 tokens -> Exceeds remaining 100 quota -> ValueError
    with pytest.raises(ValueError, match="Token quota exceeded"):
        gateway.delegate_execution(grant.grant_id, "bob", "Task 2", token_cost=200)

    # Owner revokes grant
    revoked = gateway.revoke_grant(grant.grant_id, "alice")
    assert revoked.status == BorrowingGrantStatusEnum.REVOKED

    # Subsequent execution rejected
    with pytest.raises(ValueError, match="not active"):
        gateway.delegate_execution(grant.grant_id, "bob", "Task 3", token_cost=50)


# --- 3. Virtual Co-Dev Room Manager Tests ---


def test_virtual_room_manager_lifecycle_and_port_relay(
    room_manager: VirtualCoDevRoomManager,
) -> None:
    room_id = "room-co-dev-99"

    # 1. Create Room
    state = room_manager.create_room(room_id=room_id, name="NextGen AI App")
    assert state.room_id == room_id
    assert state.name == "NextGen AI App"

    # 2. Join participants (Tri-partitioning: Human + Agents)
    alice = room_manager.join_room(
        room_id=room_id,
        participant_id="human-alice",
        name="Alice Engineer",
        role=ParticipantRoleEnum.HUMAN_DEV,
        local_identity_bound=True,
    )
    assert alice.is_active is True

    agent_coder = room_manager.join_room(
        room_id=room_id,
        participant_id="agent-coder-01",
        name="Fullstack Coder",
        role=ParticipantRoleEnum.AGENT_WORKER,
    )
    assert agent_coder.role == ParticipantRoleEnum.AGENT_WORKER

    # 3. Register sandbox live preview port relay
    relay = room_manager.register_service_relay(
        room_id=room_id,
        service_name="web-frontend",
        port=3000,
        launched_by_id="agent-coder-01",
    )
    assert relay.port == 3000
    assert "preview" in relay.live_preview_url

    # 4. Acquire file lock through integrated room lock engine
    lock = room_manager.lock_engine.acquire_lock(
        file_path="src/App.tsx",
        holder_id="agent-coder-01",
        holder_role=ParticipantRoleEnum.AGENT_WORKER,
        scope=LockScopeEnum.FILE_FULL,
    )
    assert lock.file_path == "src/App.tsx"

    # 5. Check unified room state
    snap = room_manager.get_room_state(room_id)
    assert len(snap.participants) == 2
    assert len(snap.active_locks) == 1
    assert len(snap.service_relays) == 1

    # 6. Verify audit activity logs
    events = room_manager.list_activity_events(room_id)
    assert len(events) >= 3
    event_types = [e.event_type for e in events]
    assert "room_created" in event_types
    assert "participant_joined" in event_types
    assert "service_relay_registered" in event_types

    # 7. Leave room
    left = room_manager.leave_room(room_id, "human-alice")
    assert left is True
    snap2 = room_manager.get_room_state(room_id)
    alice_part = next(p for p in snap2.participants if p.participant_id == "human-alice")
    assert alice_part.is_active is False

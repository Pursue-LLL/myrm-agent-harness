"""Unit tests for the Lightweight P2P Agent Socket Mesh Protocol."""

import tempfile
import time

import pytest

from myrm_agent_harness.agent.sub_agents.socket_mesh import (
    Envelope,
    EnvelopeType,
    MeshRegistry,
    PeerStatus,
    RegistryEntry,
    SocketMeshNode,
)


def test_registry_register_and_list_peers() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        registry = MeshRegistry(base_dir=tmp_dir, stale_threshold_seconds=10.0)

        entry1 = RegistryEntry(
            session_id="session-p1",
            name="planner",
            purpose="System Architecture & Strategy",
            model="gpt-5",
            pid=1234,
            endpoint=registry.get_endpoint("session-p1"),
            cwd=tmp_dir,
            started_at=time.time(),
            heartbeat_at=time.time(),
        )
        entry2 = RegistryEntry(
            session_id="session-c1",
            name="coder",
            purpose="Backend & Harness Implementation",
            model="claude-3.7-sonnet",
            pid=5678,
            endpoint=registry.get_endpoint("session-c1"),
            cwd=tmp_dir,
            started_at=time.time(),
            heartbeat_at=time.time(),
        )

        registry.register_peer("alpha", entry1)
        registry.register_peer("alpha", entry2)

        peers = registry.list_peers("alpha")
        assert len(peers) == 2
        names = {p.name for p in peers}
        assert "planner" in names
        assert "coder" in names

        # Test heartbeat touch
        assert registry.touch_heartbeat("alpha", "planner", context_used_pct=42.5, queue_depth=3)
        updated = registry.get_peer("alpha", "planner")
        assert updated is not None
        assert updated.context_used_pct == 42.5
        assert updated.queue_depth == 3


def test_registry_stale_and_cleanup() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        registry = MeshRegistry(
            base_dir=tmp_dir,
            stale_threshold_seconds=0.1,
            offline_threshold_seconds=0.3,
        )

        entry = RegistryEntry(
            session_id="session-z1",
            name="zombie",
            purpose="Idle Background Process",
            model="mini",
            pid=9999,
            endpoint=registry.get_endpoint("session-z1"),
            cwd=tmp_dir,
            started_at=time.time() - 1.0,
            heartbeat_at=time.time() - 0.5,
        )
        registry.register_peer("beta", entry)

        # Should be detected as stale or offline
        peers = registry.list_peers("beta", auto_mark_stale=True)
        assert len(peers) == 1
        assert peers[0].status in (PeerStatus.STALE, PeerStatus.OFFLINE)

        # Cleanup should remove the old peer
        cleaned = registry.cleanup_stale_peers("beta", max_age_seconds=0.2)
        assert cleaned == 1
        assert len(registry.list_peers("beta")) == 0


def test_envelope_serialization_and_deserialization() -> None:
    env = Envelope(
        msg_id="msg-unique-42",
        type=EnvelopeType.PROMPT,
        sender_session="sess-100",
        sender_name="alice",
        sender_endpoint="/tmp/alice.sock",
        target_name="bob",
        hops=1,
        prompt="Design a Byzantine-fault-tolerant consensus DAG.",
    )

    data = env.to_dict()
    assert data["msg_id"] == "msg-unique-42"
    assert data["hops"] == 1
    assert data["prompt"] == "Design a Byzantine-fault-tolerant consensus DAG."

    restored = Envelope.from_dict(data)
    assert restored.msg_id == env.msg_id
    assert restored.type == env.type
    assert restored.sender_name == env.sender_name
    assert restored.target_name == env.target_name
    assert restored.hops == env.hops
    assert restored.prompt == env.prompt


@pytest.mark.asyncio
async def test_p2p_prompt_and_reply() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        registry = MeshRegistry(base_dir=tmp_dir)

        node_a = SocketMeshNode(
            name="orchestrator",
            project="test_proj",
            purpose="Mission Coordinator",
            registry=registry,
        )
        node_b = SocketMeshNode(
            name="worker",
            project="test_proj",
            purpose="Compute Worker",
            registry=registry,
        )

        node_a.start()
        node_b.start()

        try:
            # Check discovery
            peers = node_a.coms_list()
            assert len(peers) == 2

            # node_a sends prompt to node_b
            send_res = await node_a.coms_send(
                target_name="worker",
                prompt="Compute SHA-256 hash of project code.",
            )
            assert send_res.success is True
            msg_id = send_res.msg_id
            assert bool(msg_id) is True

            # node_b should have received the inbound envelope
            assert len(node_b._inbound_messages) == 1
            inbound = node_b._inbound_messages[0]
            assert inbound.msg_id == msg_id
            assert inbound.prompt == "Compute SHA-256 hash of project code."

            # node_b replies
            reply_res = await node_b.coms_reply(
                inbound_envelope=inbound,
                response_text="Hash computed: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            )
            assert reply_res.success is True

            # node_a awaits reply
            await_res = await node_a.coms_await(msg_id=msg_id, timeout_seconds=5.0)
            assert await_res.success is True
            assert "Hash computed" in str(await_res.response)
            assert await_res.hops == 1
        finally:
            node_a.stop()
            node_b.stop()


@pytest.mark.asyncio
async def test_anti_loop_hops_limit() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        registry = MeshRegistry(base_dir=tmp_dir)
        node = SocketMeshNode(name="relay", project="loop_test", registry=registry)
        node.start()

        try:
            # Envelope already with 5 hops
            high_hop_envelope = Envelope(
                msg_id="loop-msg-01",
                type=EnvelopeType.PROMPT,
                sender_name="upstream",
                target_name="relay",
                hops=5,
                prompt="Forward me again",
            )

            # Node tries to reply or forward -> next hop is 6 > MAX_HOPS (5)
            reply_res = await node.coms_reply(
                inbound_envelope=high_hop_envelope,
                response_text="Forwarded again",
            )
            assert reply_res.success is False
            assert "Hop limit exceeded" in str(reply_res.error)
            assert "Anti-loop triggered" in str(reply_res.error)
        finally:
            node.stop()


@pytest.mark.asyncio
async def test_ping_pong_agent_card() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        registry = MeshRegistry(base_dir=tmp_dir)
        node_ping = SocketMeshNode(name="sentinel", project="ping_proj", registry=registry)
        node_pong = SocketMeshNode(
            name="target_bot",
            project="ping_proj",
            purpose="Vector Database Specialist",
            model="text-embedding-3",
            registry=registry,
        )

        node_ping.start()
        node_pong.start()

        try:
            ping_res = await node_ping.coms_ping("target_bot", timeout_seconds=5.0)
            assert ping_res.success is True
            assert "PONG from target_bot" in str(ping_res.response)
            assert "Vector Database Specialist" in str(ping_res.response)
        finally:
            node_ping.stop()
            node_pong.stop()

"""Unit tests for AgentMentionDualModeReadOnlySnapshotAndBidiChannel.

Validates dual-mode mention semantics: read-only context snapshot extraction
without disturbing target agents vs. active bi-directional peer communication
channels with TTL windows and delivery receipts.
"""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.runtime.context.agent_mention_dual_mode_router import (
    AgentMentionDualModeRouter,
)
from myrm_agent_harness.runtime.context.agent_mention_types import (
    AgentMentionMode,
    NormalizedAgentMention,
)
from myrm_agent_harness.runtime.context.bidi_agent_channel_gateway import (
    BidiAgentChannelGateway,
)
from myrm_agent_harness.runtime.context.project_hierarchy_session_types import (
    ArchivedMessageEntry,
)
from myrm_agent_harness.runtime.context.read_only_snapshot_capturer import (
    ReadOnlySnapshotCapturer,
)


def test_read_only_snapshot_capturer_isolation_and_formatting() -> None:
    capturer = ReadOnlySnapshotCapturer()
    now = time.time()

    msgs = [
        ArchivedMessageEntry(
            message_id="m1",
            session_id="sess_target_backend",
            role="user",
            content="Deploy database migration v2",
            timestamp=now - 100,
        ),
        ArchivedMessageEntry(
            message_id="m2",
            session_id="sess_target_backend",
            role="assistant",
            content="Migration executed successfully; created table auth_tokens.",
            file_references=("migrations/002_tokens.sql",),
            timestamp=now - 50,
        ),
    ]

    snapshot = capturer.capture_snapshot(
        source_session_id="sess_current_frontend",
        target_session_id="sess_target_backend",
        messages=msgs,
        workspace_path="/workspace/backend",
        max_chars=2000,
    )

    assert snapshot.source_session_id == "sess_current_frontend"
    assert snapshot.target_session_id == "sess_target_backend"
    assert snapshot.retained_messages_count == 2
    assert "auth_tokens" in snapshot.summary_markdown
    assert "migrations/002_tokens.sql" in snapshot.summary_markdown

    prompt_block = capturer.format_mention_prompt_block(snapshot)
    assert "<agent_reference mode='read_only'>" in prompt_block
    assert "Peer Session Reference: sess_target_backend" in prompt_block
    assert "The peer agent is unaware of this inquiry" in prompt_block
    assert "Workspace Reference: /workspace/backend" in prompt_block


def test_bidi_agent_channel_gateway_lifecycle_and_messaging() -> None:
    gateway = BidiAgentChannelGateway(default_ttl_seconds=3600.0)

    # 1. Open bidirectional channel
    link = gateway.open_channel("session_agent_a", "session_agent_b")
    assert link.is_active is True
    assert link.session_a in ("session_agent_a", "session_agent_b")
    assert link.session_b in ("session_agent_a", "session_agent_b")
    assert link.expires_at > link.created_at

    # 2. Agent A sends message to Agent B
    frame_1 = gateway.send_peer_message(
        channel_id=link.channel_id,
        sender_session_id="session_agent_a",
        payload="What is the schema of auth_tokens table?",
    )
    assert frame_1.sender_session_id == "session_agent_a"
    assert frame_1.receiver_session_id == "session_agent_b"
    assert frame_1.acknowledged is False

    # 3. Agent B polls unread messages
    unreads_b = gateway.poll_peer_messages(link.channel_id, receiver_session_id="session_agent_b")
    assert len(unreads_b) == 1
    assert unreads_b[0].payload == "What is the schema of auth_tokens table?"

    # Second poll should be empty (already acknowledged)
    unreads_again = gateway.poll_peer_messages(link.channel_id, receiver_session_id="session_agent_b")
    assert len(unreads_again) == 0

    # 4. Agent B replies to Agent A
    gateway.send_peer_message(
        channel_id=link.channel_id,
        sender_session_id="session_agent_b",
        payload="Fields are id UUID, token VARCHAR, expires_at TIMESTAMP.",
    )
    unreads_a = gateway.poll_peer_messages(link.channel_id, receiver_session_id="session_agent_a")
    assert len(unreads_a) == 1
    assert "expires_at TIMESTAMP" in unreads_a[0].payload

    # 5. Unauthorized session sender error
    with pytest.raises(PermissionError):
        gateway.send_peer_message(
            channel_id=link.channel_id,
            sender_session_id="session_agent_intruder",
            payload="Malicious message",
        )

    # 6. Close channel
    assert gateway.close_channel(link.channel_id) is True
    with pytest.raises(RuntimeError):
        gateway.send_peer_message(
            channel_id=link.channel_id,
            sender_session_id="session_agent_a",
            payload="Message after closure",
        )


def test_agent_mention_dual_mode_router_end_to_end() -> None:
    # Set up mock message provider for historical session lookups
    def mock_provider(session_id: str) -> list[ArchivedMessageEntry]:
        if session_id == "sess_backend":
            return [
                ArchivedMessageEntry(
                    message_id="bm1",
                    session_id="sess_backend",
                    role="assistant",
                    content="REST API endpoints running on :8080/api/v1/auth",
                )
            ]
        return []

    router = AgentMentionDualModeRouter(message_provider=mock_provider)

    # Prompt containing both explicit mentions and text embedded @session
    explicit = [
        NormalizedAgentMention(
            target_session_id="sess_backend",
            mode=AgentMentionMode.READ_ONLY,
            mention_label="Backend Service",
        ),
        NormalizedAgentMention(
            target_session_id="sess_tester",
            mode=AgentMentionMode.BIDIRECTIONAL,
            mention_label="QA Test Agent",
        ),
    ]

    prompt_text = "Align our UI styles and @session=sess_backend for API docs."
    normalized = router.normalize_mentions(explicit, prompt_text=prompt_text)
    assert len(normalized) == 2

    # Route and apply to prompt
    enhanced_prompt, audit = router.route_and_apply(
        current_session_id="sess_frontend_main",
        prompt_text="Please generate the login form.",
        mentions=normalized,
        workspace_path="/workspace/frontend",
    )

    # Verify read-only section injected for sess_backend
    assert "<agent_reference mode='read_only'>" in enhanced_prompt
    assert "sess_backend" in enhanced_prompt
    assert "REST API endpoints running" in enhanced_prompt

    # Verify bi-directional offer section appended for sess_tester
    assert "<bidi_agent_channel" in enhanced_prompt
    assert "sess_tester" in enhanced_prompt
    assert "QA Test Agent" in enhanced_prompt

    # Verify audit metrics
    assert audit.total_mentions == 2
    assert audit.read_only_injected == 1
    assert audit.bidi_channels_linked == 1
    assert audit.bidi_channels_rejected == 0
    assert audit.captured_tokens_approx > 0


def test_agent_mention_router_dedup_and_self_mention() -> None:
    router = AgentMentionDualModeRouter()

    # Self-mention should be bypassed during route_and_apply
    mentions = [
        NormalizedAgentMention(
            target_session_id="sess_self",
            mode=AgentMentionMode.READ_ONLY,
        ),
        NormalizedAgentMention(
            target_session_id="sess_self",
            mode=AgentMentionMode.BIDIRECTIONAL,
        ),
    ]
    deduped = router.normalize_mentions(mentions)
    assert len(deduped) == 1
    # BIDIRECTIONAL mode takes precedence
    assert deduped[0].mode == AgentMentionMode.BIDIRECTIONAL

    # Applying self mention yields 0 injected
    prompt, audit = router.route_and_apply(
        current_session_id="sess_self",
        prompt_text="Self work",
        mentions=deduped,
    )
    assert audit.read_only_injected == 0
    assert audit.bidi_channels_linked == 0
    assert prompt == "Self work"

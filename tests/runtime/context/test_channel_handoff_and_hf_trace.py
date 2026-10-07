"""Unit tests for CrossPlatformChannelHandoffProtocol and HuggingFaceTraceViewerExportPack (Item 101).

Validates platform-native thread anchor synthesis, verifiable session handoff tokens,
HuggingFace Agent Trace specification compliance, credential redaction,
and turn-scoped media pointer anti-bloat lifecycles.
"""

import json

from myrm_agent_harness.runtime.context.channel_handoff_and_hf_trace_engine import (
    CrossPlatformChannelHandoffCoordinator,
    HuggingFaceAgentTraceExporter,
)
from myrm_agent_harness.runtime.context.channel_handoff_and_hf_trace_types import (
    ChannelThreadKind,
    HandoffSessionEnvelope,
    TargetChannelType,
)
from myrm_agent_harness.runtime.context.media_pointer_lifecycle_manager import (
    MediaPointerLifecycleManager,
)
from myrm_agent_harness.runtime.context.session_lifecycle_log_archiver_types import (
    SessionExecutionTurn,
    TokenCostBillingSnapshot,
    ToolExecutionLogEntry,
    ToolExecutionStatus,
)


def _sample_conversation_turn() -> SessionExecutionTurn:
    """Helper to construct an execution turn with tool invocations."""
    tool = ToolExecutionLogEntry(
        call_id="call_trace_01",
        tool_name="github_repo_inspect",
        arguments={"repo": "myrm/core", "token": "ghp_1234567890123456789012345678"},
        result_payload='{"status": "ok", "api_key": "sk-proj999888777666555444333222111"}',
        duration_ms=45.2,
        status=ToolExecutionStatus.SUCCESS,
        timestamp="2026-10-07T11:00:01Z",
    )
    return SessionExecutionTurn(
        turn_id=1,
        user_input="Inspect GitHub repo with my key sk-proj111222333444555666777888",
        assistant_response="Inspection complete. Secrets checked.",
        tool_calls=[tool],
        token_billing=TokenCostBillingSnapshot(500, 100, 400, 0.001),
        errors=[],
        timestamp="2026-10-07T11:00:05Z",
    )


def test_cross_platform_thread_anchor_generation() -> None:
    """Verify platform-specific thread anchor synthesis."""
    coord = CrossPlatformChannelHandoffCoordinator()
    sess_id = "session-abcdef12-3456"

    # Telegram -> Forum Topic
    tg_anchor = coord.create_thread_anchor(sess_id, TargetChannelType.TELEGRAM)
    assert tg_anchor.thread_kind == ChannelThreadKind.FORUM_TOPIC
    assert "topic_" in tg_anchor.thread_identifier
    assert "topic_name" in tg_anchor.platform_metadata

    # Discord -> Auto-archive thread
    dc_anchor = coord.create_thread_anchor(sess_id, TargetChannelType.DISCORD)
    assert dc_anchor.thread_kind == ChannelThreadKind.AUTO_ARCHIVE_THREAD
    assert "thread_" in dc_anchor.thread_identifier
    assert dc_anchor.platform_metadata["auto_archive_minutes"] == "1440"

    # Slack -> Anchor message
    sl_anchor = coord.create_thread_anchor(sess_id, TargetChannelType.SLACK)
    assert sl_anchor.thread_kind == ChannelThreadKind.ANCHOR_MESSAGE
    assert sl_anchor.parent_message_id is not None

    # Feishu -> Topic container
    fs_anchor = coord.create_thread_anchor(sess_id, TargetChannelType.FEISHU)
    assert fs_anchor.thread_kind == ChannelThreadKind.TOPIC_CONTAINER

    # Web/CLI -> Direct channel
    web_anchor = coord.create_thread_anchor(sess_id, TargetChannelType.WEB_UI)
    assert web_anchor.thread_kind == ChannelThreadKind.DIRECT_CHANNEL


def test_handoff_envelope_issuance_and_cryptographic_resumption_verification() -> None:
    """Verify handoff token generation and tamper detection."""
    coord = CrossPlatformChannelHandoffCoordinator(signing_secret="secure-test-secret")
    sess_id = "sess_prod_888"

    envelope = coord.initiate_handoff(
        session_id=sess_id,
        source_channel=TargetChannelType.WEB_UI,
        target_channel=TargetChannelType.TELEGRAM,
        turns_count=5,
        state_fingerprint="sha256_hash_abc",
    )

    assert envelope.session_id == sess_id
    assert envelope.source_channel == TargetChannelType.WEB_UI
    assert envelope.target_channel == TargetChannelType.TELEGRAM
    assert len(envelope.resumption_token) == 64

    # Legitimate token passes verification
    assert coord.verify_resumption_token(envelope) is True

    # Tampered envelope fails verification
    tampered = HandoffSessionEnvelope(
        session_id=sess_id,
        source_channel=TargetChannelType.WEB_UI,
        target_channel=TargetChannelType.DISCORD,  # Tampered target
        thread_anchor=envelope.thread_anchor,
        resumption_token=envelope.resumption_token,
        state_fingerprint=envelope.state_fingerprint,
        created_at=envelope.created_at,
        context_turns_count=envelope.context_turns_count,
    )
    assert coord.verify_resumption_token(tampered) is False


def test_huggingface_agent_trace_export_and_jsonl_structure() -> None:
    """Verify conversion to HuggingFace Agent Trace Viewer specification."""
    exporter = HuggingFaceAgentTraceExporter()
    turn = _sample_conversation_turn()

    steps = exporter.export_trace_steps([turn], redact=False)
    assert len(steps) == 3

    # Step 1: User
    assert steps[0].step_number == 1
    assert steps[0].role == "user"
    assert steps[0].thought is None

    # Step 2: Agent Tool Invocation
    assert steps[1].step_number == 2
    assert steps[1].role == "agent"
    assert steps[1].action_tool == "github_repo_inspect"
    assert steps[1].action_input == {
        "repo": "myrm/core",
        "token": "ghp_1234567890123456789012345678",
    }
    assert steps[1].observation is not None
    assert steps[1].duration_ms == 45.2

    # Step 3: Assistant Final Answer
    assert steps[2].step_number == 3
    assert steps[2].role == "assistant"
    assert steps[2].final_output == "Inspection complete. Secrets checked."

    # Validate JSONL output stream
    jsonl_str = exporter.export_trace_jsonl([turn], redact=False)
    lines = jsonl_str.strip().split("\n")
    assert len(lines) == 3
    for line in lines:
        parsed = json.loads(line)
        assert "step" in parsed
        assert "role" in parsed


def test_hf_trace_exporter_secret_redaction() -> None:
    """Verify --redact scrubs sensitive API keys in all trace steps."""
    exporter = HuggingFaceAgentTraceExporter()
    turn = _sample_conversation_turn()

    jsonl_redacted = exporter.export_trace_jsonl([turn], redact=True)

    # Ensure sensitive credentials are eradicated
    assert "sk-proj111222333444555666777888" not in jsonl_redacted
    assert "ghp_1234567890123456789012345678" not in jsonl_redacted
    assert "sk-proj999888777666555444333222111" not in jsonl_redacted

    # Ensure placeholder is injected
    assert "[REDACTED_SECRET]" in jsonl_redacted


def test_media_pointer_lifecycle_and_multimodal_context_anti_bloat() -> None:
    """Verify heavy multimodal payloads are transformed into lightweight pointers."""
    manager = MediaPointerLifecycleManager(cache_root_dir="/cache/multimodal")

    # Construct bulky mock image data URL (100+ Base64 chars)
    bulky_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" * 5
    raw_data_url = f"data:image/png;base64,{bulky_b64}"
    message_content = f"Look at this screenshot:\n{raw_data_url}\nWhat does it show?"

    # Turn 1: Process and register media
    processed_turn1, pointers_turn1 = manager.process_turn_content(
        message_content, current_turn=1, default_caption="System Architecture Diagram"
    )
    assert len(pointers_turn1) == 1
    media_pointer = pointers_turn1[0]
    assert media_pointer.mime_type == "image/png"
    assert media_pointer.turn_introduced == 1
    assert "id=med_" in processed_turn1
    assert "[MediaPointer:" in processed_turn1

    # Turn 2: Subsequent conversation turn referencing original message
    processed_turn2, pointers_turn2 = manager.process_turn_content(
        message_content, current_turn=2
    )
    assert len(pointers_turn2) == 1
    # Bulky base64 payload must NOT appear in output
    assert bulky_b64 not in processed_turn2
    # Replaced by compact pointer directive
    assert media_pointer.to_pointer_directive() in processed_turn2
    assert manager.total_bytes_managed() > 0

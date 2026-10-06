"""Unit tests for internal/external message separation and context transformation pipeline."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.internal_external_message_pipeline import (
    InternalExternalMessagePipeline,
)
from myrm_agent_harness.runtime.context.internal_external_message_pipeline_types import (
    AgentMessage,
    AgentMessageKind,
    TransformPipelineOptions,
)


@pytest.fixture
def pipeline() -> InternalExternalMessagePipeline:
    return InternalExternalMessagePipeline()


def test_agent_message_all_seven_kinds_creation() -> None:
    """Validate rich domain creation of all 7 internal AgentMessage kinds."""
    kinds = [
        AgentMessageKind.USER,
        AgentMessageKind.ASSISTANT,
        AgentMessageKind.TOOL_EXECUTION,
        AgentMessageKind.SYSTEM_NOTIFICATION,
        AgentMessageKind.CONFIG_MUTATION,
        AgentMessageKind.BRANCH_MARKER,
        AgentMessageKind.HUMAN_APPROVAL_GATE,
    ]
    messages = [
        AgentMessage(
            message_id=f"msg_{i}",
            kind=kind,
            content=f"Payload for {kind.value}",
            metadata={"source_ui": "desktop_drawer"},
        )
        for i, kind in enumerate(kinds)
    ]
    assert len(messages) == 7
    assert messages[0].kind == AgentMessageKind.USER
    assert messages[4].kind == AgentMessageKind.CONFIG_MUTATION
    assert messages[6].kind == AgentMessageKind.HUMAN_APPROVAL_GATE


def test_drop_incomplete_streaming_messages(pipeline: InternalExternalMessagePipeline) -> None:
    """Validate that incomplete streaming chunks are pruned during context transformation."""
    messages = [
        AgentMessage(
            message_id="m1",
            kind=AgentMessageKind.USER,
            content="Hello",
        ),
        AgentMessage(
            message_id="m2",
            kind=AgentMessageKind.ASSISTANT,
            content="I am thinking...",
            is_streaming_incomplete=True,
        ),
        AgentMessage(
            message_id="m3",
            kind=AgentMessageKind.ASSISTANT,
            content="Hello there! Finished answer.",
            is_streaming_incomplete=False,
        ),
    ]

    transformed = pipeline.transform_context(messages)
    assert len(transformed) == 2
    assert [m.message_id for m in transformed] == ["m1", "m3"]


def test_tool_output_truncation_preserves_head_and_tail(
    pipeline: InternalExternalMessagePipeline,
) -> None:
    """Validate that oversized tool execution output is folded to preserve context budget."""
    head_content = "SUCCESS_START: log entries beginning\n" * 10
    middle_content = "REDUNDANT_SPAM_DATA: verbose dump\n" * 200
    tail_content = "SUCCESS_END: status 0 completed with artifact #99"
    full_output = f"{head_content}{middle_content}{tail_content}"

    tool_msg = AgentMessage(
        message_id="tool_1",
        kind=AgentMessageKind.TOOL_EXECUTION,
        content=full_output,
        tool_call_id="call_abc",
        tool_name="bash_exec",
    )

    options = TransformPipelineOptions(
        max_tool_output_chars=500,
        truncate_head_ratio=0.3,
        truncate_tail_ratio=0.3,
    )
    transformed = pipeline.transform_context([tool_msg], options=options)

    assert len(transformed) == 1
    sanitized_output = transformed[0].content
    assert len(sanitized_output) < len(full_output)
    assert "Output truncated:" in sanitized_output
    assert "SUCCESS_START:" in sanitized_output
    assert "SUCCESS_END:" in sanitized_output


def test_internal_meta_events_strictly_isolated_from_llm(
    pipeline: InternalExternalMessagePipeline,
) -> None:
    """Validate 100% zero-leakage of config mutations, branch markers, and approval gates to external LLM."""
    messages = [
        AgentMessage(
            message_id="m1",
            kind=AgentMessageKind.USER,
            content="Run deploy script",
            metadata={"ui_client_ver": "2.4.1", "auth_token_ref": "secret_ref"},
        ),
        AgentMessage(
            message_id="m2",
            kind=AgentMessageKind.CONFIG_MUTATION,
            content="Switched model from claude-sonnet to gpt-4o for code-review",
        ),
        AgentMessage(
            message_id="m3",
            kind=AgentMessageKind.BRANCH_MARKER,
            content="Branched session to feature/quick-fix at node node_49",
        ),
        AgentMessage(
            message_id="m4",
            kind=AgentMessageKind.HUMAN_APPROVAL_GATE,
            content="HITL Gate: user approved dangerous execution rm -rf /tmp/cache",
        ),
        AgentMessage(
            message_id="m5",
            kind=AgentMessageKind.ASSISTANT,
            content="Deployment is complete.",
        ),
    ]

    llm_msgs, metrics = pipeline.convert_to_llm(messages)

    # Only USER and ASSISTANT messages should be forwarded
    assert len(llm_msgs) == 2
    assert llm_msgs[0].role == "user"
    assert llm_msgs[0].content == "Run deploy script"
    # Metadata dictionary is never included in external protocol
    assert not hasattr(llm_msgs[0], "metadata") or getattr(llm_msgs[0], "metadata", None) is None

    assert llm_msgs[1].role == "assistant"
    assert llm_msgs[1].content == "Deployment is complete."

    assert metrics.pruned_meta_events_count == 3
    assert metrics.output_llm_count == 2
    assert metrics.tokens_saved_estimate > 0


def test_system_notification_policy_and_end_to_end_pipeline(
    pipeline: InternalExternalMessagePipeline,
) -> None:
    """Validate end-to-end pipeline execution with system notifications and metrics calculation."""
    messages = [
        AgentMessage(
            message_id="m1",
            kind=AgentMessageKind.SYSTEM_NOTIFICATION,
            content="Memory usage watermark at 82%",
        ),
        AgentMessage(
            message_id="m2",
            kind=AgentMessageKind.USER,
            content="List files",
        ),
        AgentMessage(
            message_id="m3",
            kind=AgentMessageKind.ASSISTANT,
            content="",
            tool_call_id="call_list_01",
            tool_name="list_dir",
            tool_arguments='{"path": "/src"}',
        ),
        AgentMessage(
            message_id="m4",
            kind=AgentMessageKind.TOOL_EXECUTION,
            content="file_a.py\nfile_b.py\nfile_c.py\n" * 50,
            tool_call_id="call_list_01",
            tool_name="list_dir",
        ),
    ]

    # Case A: By default system notification is pruned
    llm_msgs_default, metrics_default = pipeline.execute_pipeline(
        messages,
        options=TransformPipelineOptions(max_tool_output_chars=100),
    )
    assert metrics_default.pruned_meta_events_count == 1
    assert len(llm_msgs_default) == 3
    roles = [m.role for m in llm_msgs_default]
    assert roles == ["user", "assistant", "tool"]
    assert llm_msgs_default[1].tool_calls is not None
    assert llm_msgs_default[1].tool_calls[0].name == "list_dir"
    assert llm_msgs_default[2].tool_call_id == "call_list_01"
    assert metrics_default.truncated_tool_chars > 0

    # Case B: When allow_system_notifications is True
    llm_msgs_allowed, metrics_allowed = pipeline.execute_pipeline(
        messages,
        options=TransformPipelineOptions(
            max_tool_output_chars=100,
            allow_system_notifications=True,
        ),
    )
    assert metrics_allowed.pruned_meta_events_count == 0
    assert len(llm_msgs_allowed) == 4
    assert llm_msgs_allowed[0].role == "system"
    assert "Memory usage watermark" in llm_msgs_allowed[0].content

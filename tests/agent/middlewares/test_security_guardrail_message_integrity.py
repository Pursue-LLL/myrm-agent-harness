"""SecurityGuardrailMiddleware: tool results made of content blocks, and rewrites that change only the content."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.middlewares._session_context import reset_terminal_errors, set_security_config
from myrm_agent_harness.agent.middlewares.security.security_guardrail_middleware import SecurityGuardrailMiddleware
from myrm_agent_harness.agent.security.types import PIIAction, PrivacyPolicy, SecurityConfig

AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYzEXAMPLEKEY"
ANTHROPIC_KEY = "sk-ant-abcdefghijklmnopqrstuvwxyz0123456789"
PNG_BLOCK = {"type": "image", "base64": "iVBORw0KGgo=", "mime_type": "image/png"}

LEAKY_TEXTS = [
    (f"AWS_SECRET_ACCESS_KEY={AWS_SECRET}", AWS_SECRET),
    (f'{{"SecretAccessKey": "{AWS_SECRET}", "UserName": "Bob"}}', AWS_SECRET),
    (f"the key is {ANTHROPIC_KEY}", ANTHROPIC_KEY),
]
LEAKY_IDS = ["env-assignment", "prefixed-json-key", "provider-key"]


def _turn(tool_message: ToolMessage) -> dict[str, list[BaseMessage]]:
    """A state where *tool_message* is the fresh result of the last tool call."""
    call = {"id": tool_message.tool_call_id, "name": "bash", "args": {}}
    return {"messages": [HumanMessage(content="run it"), AIMessage(content="", tool_calls=[call]), tool_message]}


def _fields_except_content(message: BaseMessage) -> dict[str, object]:
    return message.model_dump(exclude={"content"})


@pytest.fixture(autouse=True)
def _clean_session() -> Iterator[None]:
    reset_terminal_errors()
    set_security_config(None)
    yield
    set_security_config(None)
    reset_terminal_errors()


class TestToolResultBlocks:
    """A tool result is a list of blocks when it carries an image (a chart, a screenshot) next to its text."""

    mw = SecurityGuardrailMiddleware()

    @pytest.mark.parametrize(("text", "secret"), LEAKY_TEXTS, ids=LEAKY_IDS)
    def test_text_block_is_redacted_and_the_image_is_left_alone(self, text: str, secret: str) -> None:
        state = _turn(ToolMessage(content=[{"type": "text", "text": text}, PNG_BLOCK], tool_call_id="tc1"))

        result = self.mw.before_model(state, None)

        assert result is not None
        text_block, image_block = result["messages"][-1].content
        assert secret not in text_block["text"]
        assert "[REDACTED:" in text_block["text"]
        assert image_block == PNG_BLOCK

    def test_every_text_block_is_scanned_including_bare_strings(self) -> None:
        content = [
            {"type": "text", "text": f"AWS_SECRET_ACCESS_KEY={AWS_SECRET}"},
            f"leaked {ANTHROPIC_KEY}",
            PNG_BLOCK,
            {"type": "text", "text": "nothing to hide"},
        ]

        result = self.mw.before_model(_turn(ToolMessage(content=content, tool_call_id="tc1")), None)

        assert result is not None
        blocks = result["messages"][-1].content
        assert AWS_SECRET not in blocks[0]["text"]
        assert ANTHROPIC_KEY not in blocks[1]
        assert blocks[2:] == [PNG_BLOCK, {"type": "text", "text": "nothing to hide"}]

    def test_a_provider_typed_text_block_is_scanned(self) -> None:
        block = {"type": "output_text", "text": f"AWS_SECRET_ACCESS_KEY={AWS_SECRET}"}

        result = self.mw.before_model(_turn(ToolMessage(content=[block], tool_call_id="tc1")), None)

        assert result is not None
        assert AWS_SECRET not in result["messages"][-1].content[0]["text"]

    def test_blocks_without_a_credential_leave_the_state_untouched(self) -> None:
        state = _turn(ToolMessage(content=[{"type": "text", "text": "plot saved"}, PNG_BLOCK], tool_call_id="tc1"))

        assert self.mw.before_model(state, None) is None

    def test_image_data_is_not_scanned(self) -> None:
        image = {"type": "image", "base64": f"AWS_SECRET_ACCESS_KEY={AWS_SECRET}", "mime_type": "image/png"}

        assert self.mw.before_model(_turn(ToolMessage(content=[image], tool_call_id="tc1")), None) is None

    @pytest.mark.parametrize(("text", "secret"), LEAKY_TEXTS, ids=LEAKY_IDS)
    def test_redacting_twice_changes_nothing_more(self, text: str, secret: str) -> None:
        state = _turn(ToolMessage(content=[{"type": "text", "text": text}, PNG_BLOCK], tool_call_id="tc1"))
        once = self.mw.before_model(state, None)
        assert once is not None

        assert self.mw.before_model(once, None) is None


class TestRewriteKeepsEverythingButTheContent:
    """A redaction changes the text. Status, metadata and ids that other layers read must come through unchanged."""

    @pytest.mark.parametrize(
        "content",
        [f"AWS_SECRET_ACCESS_KEY={AWS_SECRET}", [{"type": "text", "text": f"AWS_SECRET_ACCESS_KEY={AWS_SECRET}"}]],
        ids=["text", "blocks"],
    )
    def test_tool_message(self, content: str | list[dict[str, str]]) -> None:
        original = ToolMessage(
            content=content,
            tool_call_id="tc1",
            name="bash",
            id="tool-1",
            status="error",
            artifact={"path": "/workspace/chart.png"},
            additional_kwargs={"error_hint": "retry with --verbose"},
            response_metadata={"duration_ms": 12},
        )

        result = SecurityGuardrailMiddleware().before_model(_turn(original), None)

        assert result is not None
        redacted = result["messages"][-1]
        assert redacted.content != original.content
        assert _fields_except_content(redacted) == _fields_except_content(original)

    def test_user_message_redacted_for_pii(self) -> None:
        set_security_config(
            SecurityConfig(
                privacy_policy=PrivacyPolicy(enabled=True, s2_action=PIIAction.REDACT, s3_action=PIIAction.REDACT)
            )
        )
        original = HumanMessage(
            content="My phone is 13812345678 and my email is test@example.com",
            id="human-1",
            additional_kwargs={"marks": ["trap_shield"], "retention": "persistent"},
        )

        result = SecurityGuardrailMiddleware().before_model({"messages": [original]}, None)

        assert result is not None
        redacted = result["messages"][0]
        assert "13812345678" not in redacted.content
        assert _fields_except_content(redacted) == _fields_except_content(original)

    def test_user_message_with_a_safety_caution_prefix(self) -> None:
        set_security_config(SecurityConfig(dangerous_intent_policy="hitl"))
        original = HumanMessage(
            content="drop database production;", id="human-1", additional_kwargs={"marks": ["pinned"]}
        )

        result = SecurityGuardrailMiddleware().before_model({"messages": [original]}, None)

        assert result is not None
        cautioned = result["messages"][0]
        assert cautioned.content.startswith("[SAFETY_CAUTION:")
        assert _fields_except_content(cautioned) == _fields_except_content(original)

    def test_ai_message_redacted_in_history(self) -> None:
        original = AIMessage(
            content=f"Your key is {ANTHROPIC_KEY}",
            id="ai-1",
            name="assistant",
            tool_calls=[{"id": "tc1", "name": "check", "args": {}}],
            additional_kwargs={"reasoning_content": "thinking"},
            response_metadata={"finish_reason": "stop", "model_name": "test-model"},
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )

        result = SecurityGuardrailMiddleware().after_model({"messages": [HumanMessage(content="q"), original]}, None)

        assert result is not None
        redacted = result["messages"][-1]
        assert ANTHROPIC_KEY not in redacted.content
        assert _fields_except_content(redacted) == _fields_except_content(original)

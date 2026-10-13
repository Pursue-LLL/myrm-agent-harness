"""Outbound privacy guard: PII is masked in every model call the in-loop guardrail does not cover."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.middlewares._session_context import (
    set_pseudonym_store,
    set_security_config,
)
from myrm_agent_harness.agent.middlewares.security import outbound_privacy_guard as guard_module
from myrm_agent_harness.agent.middlewares.security.outbound_privacy_guard import (
    guard_outbound_messages,
    install_outbound_privacy_guard,
    is_privacy_enforced_by_loop,
    resolve_privacy_policy,
    sanitize_outbound_text,
    set_process_privacy_policy,
)
from myrm_agent_harness.agent.middlewares.security.security_guardrail_middleware import (
    SecurityGuardrailMiddleware,
    _redact_ai_text,
)
from myrm_agent_harness.agent.middlewares.security.user_input_guard import screen_user_input
from myrm_agent_harness.agent.security.types import PIIAction, PrivacyPolicy, SecurityConfig
from myrm_agent_harness.core.security.detection.pseudonym_store import PseudonymStore
from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.adapters.chat_model.outbound_guard import set_outbound_message_guard

WITH_S3 = "我叫张三，手机13812345678，身份证11010519491231002X，邮箱zhang@example.com，帮我写请假邮件"
ONLY_S2 = "手机13812345678，邮箱zhang@example.com，帮我订会议室"
PHONE = "13812345678"
ID_CARD = "11010519491231002X"
DATA_URL = "data:image/png;base64,AAAA"


def _policy(s2: PIIAction = PIIAction.REDACT, s3: PIIAction = PIIAction.REDACT) -> PrivacyPolicy:
    return PrivacyPolicy(enabled=True, s2_action=s2, s3_action=s3)


@pytest.fixture(autouse=True)
def _clean_privacy_state() -> Iterator[None]:
    def reset() -> None:
        set_security_config(None)
        set_pseudonym_store(None)
        set_process_privacy_policy(None)
        set_outbound_message_guard(None)

    reset()
    yield
    reset()


class TestPolicyResolution:
    def test_no_policy_anywhere_is_disabled(self) -> None:
        assert resolve_privacy_policy().enabled is False

    def test_process_policy_serves_calls_outside_any_agent_run(self) -> None:
        set_process_privacy_policy(_policy())
        assert resolve_privacy_policy().enabled is True

    def test_run_policy_wins_over_the_process_policy(self) -> None:
        set_process_privacy_policy(_policy(PIIAction.REDACT))
        set_security_config(SecurityConfig(privacy_policy=_policy(PIIAction.WARN)))
        assert resolve_privacy_policy().s2_action == PIIAction.WARN

    def test_disabled_run_policy_falls_back_to_the_process_policy(self) -> None:
        set_process_privacy_policy(_policy())
        set_security_config(SecurityConfig(privacy_policy=PrivacyPolicy(enabled=False)))
        assert resolve_privacy_policy().enabled is True


class TestGuardOutboundMessages:
    def test_masks_user_assistant_and_tool_text_but_not_system_or_developer(self) -> None:
        set_process_privacy_policy(_policy())
        messages: list[dict[str, object]] = [
            {"role": "system", "content": f"operator note {PHONE}"},
            {"role": "developer", "content": f"operator note {PHONE}"},
            {"role": "user", "content": ONLY_S2},
            {"role": "assistant", "content": f"已记录 {ONLY_S2}", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": ONLY_S2, "tool_call_id": "1"},
        ]
        guard_outbound_messages(messages)

        assert PHONE in str(messages[0]["content"]) and PHONE in str(messages[1]["content"])
        for message in messages[2:]:
            assert PHONE not in str(message["content"])
            assert "zhang@example.com" not in str(message["content"])
        assert messages[3]["tool_calls"] == [{"id": "1"}]

    def test_masks_text_blocks_and_leaves_images_and_the_source_list_alone(self) -> None:
        set_process_privacy_policy(_policy())
        image = {"type": "image_url", "image_url": {"url": DATA_URL}}
        source_blocks: list[object] = [{"type": "text", "text": ONLY_S2}, image]
        messages: list[dict[str, object]] = [{"role": "user", "content": source_blocks}]

        guard_outbound_messages(messages)

        content = messages[0]["content"]
        assert isinstance(content, list)
        assert PHONE not in str(content[0])
        assert content[1] == image
        assert source_blocks[0] == {"type": "text", "text": ONLY_S2}

    def test_a_disabled_policy_changes_nothing(self) -> None:
        messages: list[dict[str, object]] = [{"role": "user", "content": WITH_S3}]
        guard_outbound_messages(messages)
        assert messages[0]["content"] == WITH_S3

    def test_warn_leaves_s2_text_unchanged_and_default_s3_redact_still_masks(self) -> None:
        set_process_privacy_policy(_policy(PIIAction.WARN, PIIAction.REDACT))
        s2_only: list[dict[str, object]] = [{"role": "user", "content": ONLY_S2}]
        with_s3: list[dict[str, object]] = [{"role": "user", "content": WITH_S3}]

        guard_outbound_messages(s2_only)
        guard_outbound_messages(with_s3)

        assert s2_only[0]["content"] == ONLY_S2
        assert ID_CARD not in str(with_s3[0]["content"])

    def test_block_falls_back_to_redaction_instead_of_dropping_the_message(self) -> None:
        set_process_privacy_policy(_policy(PIIAction.WARN, PIIAction.BLOCK))
        messages: list[dict[str, object]] = [{"role": "user", "content": WITH_S3}]

        guard_outbound_messages(messages)

        assert isinstance(messages[0]["content"], str)
        assert ID_CARD not in messages[0]["content"]

    def test_a_loop_that_enforces_the_policy_itself_is_not_processed_twice(self) -> None:
        set_process_privacy_policy(_policy())
        messages: list[dict[str, object]] = [{"role": "user", "content": ONLY_S2}]

        with guard_module.privacy_enforced_by_loop(True):
            guard_outbound_messages(messages)

        assert messages[0]["content"] == ONLY_S2

    def test_a_failing_redaction_stops_the_call(self) -> None:
        set_process_privacy_policy(_policy())
        with (
            patch.object(guard_module, "apply_privacy_policy", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            guard_outbound_messages([{"role": "user", "content": ONLY_S2}])

    def test_sanitize_outbound_text_follows_the_resolved_policy(self) -> None:
        assert sanitize_outbound_text(ONLY_S2) == ONLY_S2
        set_process_privacy_policy(_policy())
        assert PHONE not in sanitize_outbound_text(ONLY_S2)


@pytest.mark.parametrize(
    ("s2", "s3"),
    [
        (PIIAction.WARN, PIIAction.REDACT),
        (PIIAction.REDACT, PIIAction.REDACT),
        (PIIAction.WARN, PIIAction.BLOCK),
        (PIIAction.PSEUDONYMIZE, PIIAction.PSEUDONYMIZE),
    ],
)
@pytest.mark.parametrize("raw", [WITH_S3, ONLY_S2])
def test_text_the_main_loop_already_processed_is_left_byte_identical(raw: str, s2: PIIAction, s3: PIIAction) -> None:
    """Prompt-cache safety: preheat and retries re-send main-loop text; the guard must not alter its bytes."""
    policy = _policy(s2, s3)
    set_security_config(SecurityConfig(privacy_policy=policy))
    set_pseudonym_store(PseudonymStore(":memory:"))
    screened = screen_user_input([HumanMessage(content=raw)], policy)
    main_loop_text = raw if screened is None else str(screened[0].content)
    messages: list[dict[str, object]] = [{"role": "user", "content": main_loop_text}]

    guard_outbound_messages(messages)
    once = messages[0]["content"]
    guard_outbound_messages(messages)

    assert once == main_loop_text
    assert messages[0]["content"] == once
    assert _redact_ai_text(main_loop_text) == main_loop_text


class TestLoopFlag:
    @staticmethod
    async def _flag_seen_inside_the_model_call(policy: PrivacyPolicy | None) -> tuple[bool, bool]:
        set_security_config(SecurityConfig(privacy_policy=policy) if policy else None)
        seen: list[bool] = []

        async def handler(request: object) -> str:
            seen.append(is_privacy_enforced_by_loop())
            return "response"

        request = MagicMock()
        request.messages = []
        await SecurityGuardrailMiddleware().awrap_model_call(request, handler)  # type: ignore[arg-type]
        return seen[0], is_privacy_enforced_by_loop()

    @pytest.mark.asyncio
    async def test_set_only_while_the_loop_enforces_an_enabled_policy(self) -> None:
        inside, after = await self._flag_seen_inside_the_model_call(_policy())
        assert (inside, after) == (True, False)

    @pytest.mark.asyncio
    async def test_not_set_when_the_loop_enforces_no_policy(self) -> None:
        inside, _ = await self._flag_seen_inside_the_model_call(PrivacyPolicy(enabled=False))
        assert inside is False

    @pytest.mark.asyncio
    async def test_reset_even_when_the_model_call_fails(self) -> None:
        set_security_config(SecurityConfig(privacy_policy=_policy()))
        handler = AsyncMock(side_effect=RuntimeError("provider down"))
        request = MagicMock()
        request.messages = []
        with pytest.raises(RuntimeError, match="provider down"):
            await SecurityGuardrailMiddleware().awrap_model_call(request, handler)
        assert is_privacy_enforced_by_loop() is False


class TestInstallation:
    @staticmethod
    def _wire(content: str) -> str:
        model = ChatLiteLLM.model_construct(client=MagicMock(), model="gpt-5-chat")
        message_dicts, _ = model._create_message_dicts([HumanMessage(content=content)], stop=None)
        return str(message_dicts[0]["content"])

    def test_installed_guard_masks_what_chat_litellm_puts_on_the_wire(self) -> None:
        set_process_privacy_policy(_policy())
        install_outbound_privacy_guard()
        assert PHONE not in self._wire(ONLY_S2)

    def test_install_is_idempotent(self) -> None:
        install_outbound_privacy_guard()
        install_outbound_privacy_guard()
        set_process_privacy_policy(_policy())
        assert PHONE not in self._wire(ONLY_S2)

    def test_publishing_a_process_policy_installs_the_guard(self) -> None:
        set_process_privacy_policy(_policy())
        assert PHONE not in self._wire(ONLY_S2)

    def test_enabling_privacy_for_a_run_installs_the_guard(self) -> None:
        set_security_config(SecurityConfig(privacy_policy=_policy()))
        assert PHONE not in self._wire(ONLY_S2)

    def test_nothing_is_installed_while_privacy_stays_off(self) -> None:
        set_security_config(SecurityConfig(privacy_policy=PrivacyPolicy(enabled=False)))
        assert self._wire(ONLY_S2) == ONLY_S2

    def test_a_model_message_in_the_conversation_is_masked_too(self) -> None:
        set_process_privacy_policy(_policy())
        model = ChatLiteLLM.model_construct(client=MagicMock(), model="gpt-5-chat")
        message_dicts, _ = model._create_message_dicts(
            [HumanMessage(content="hi"), AIMessage(content=f"已记录 {ONLY_S2}")], stop=None
        )
        assert PHONE not in str(message_dicts[1]["content"])

"""Memory extraction under a privacy policy: the extraction model reads masked conversation text."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent._internals.memory_extraction import auto_extract_memories
from myrm_agent_harness.agent.middlewares._session_context import set_security_config
from myrm_agent_harness.agent.middlewares.security.outbound_privacy_guard import set_process_privacy_policy
from myrm_agent_harness.agent.security.types import PIIAction, PrivacyPolicy, SecurityConfig
from myrm_agent_harness.toolkits.llms.adapters.chat_model.outbound_guard import set_outbound_message_guard

PHONE = "13812345678"
QUERY = f"我的手机是{PHONE}，邮箱zhang@example.com，请记住我喜欢周三下午开会"
REPLY = "好的，已经记住你的会议偏好，之后安排日程会优先考虑周三下午。" * 4
_EXTRACTOR = "myrm_agent_harness.toolkits.memory.strategies.extractor.extract_memories_from_conversation"


@pytest.fixture(autouse=True)
def _clean_privacy_state() -> Iterator[None]:
    def reset() -> None:
        set_security_config(None)
        set_process_privacy_policy(None)
        set_outbound_message_guard(None)

    reset()
    yield
    reset()


async def _extraction_input() -> str:
    """Run one post-turn extraction and return the conversation text handed to the extractor."""
    captured: list[str] = []

    async def fake_extract(messages: list[dict[str, str]], **_: object) -> MagicMock:
        captured.append(" ".join(m["content"] for m in messages))
        return MagicMock(memories=[], extraction_time_ms=0.0)

    manager = MagicMock()
    manager.last_cited_memory_ids = []
    with patch(_EXTRACTOR, new=fake_extract):
        await auto_extract_memories(
            query=QUERY, chat_history=None, memory_manager=manager, llm=AsyncMock(), assistant_reply=REPLY
        )
    return captured[0]


@pytest.mark.asyncio
async def test_extractor_input_is_masked_under_the_run_policy() -> None:
    set_security_config(SecurityConfig(privacy_policy=PrivacyPolicy(enabled=True, s2_action=PIIAction.REDACT)))
    text = await _extraction_input()
    assert PHONE not in text
    assert "zhang@example.com" not in text
    assert "周三下午" in text


@pytest.mark.asyncio
async def test_extractor_input_is_masked_under_the_process_policy_after_the_run_context_is_gone() -> None:
    set_process_privacy_policy(PrivacyPolicy(enabled=True, s2_action=PIIAction.REDACT))
    assert PHONE not in await _extraction_input()


@pytest.mark.asyncio
async def test_extractor_input_is_untouched_while_privacy_is_off() -> None:
    assert PHONE in await _extraction_input()

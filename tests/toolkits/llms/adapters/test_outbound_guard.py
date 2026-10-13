"""Outbound message guard: the single hook every ChatLiteLLM call passes before it leaves the process."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.adapters.chat_model.outbound_guard import (
    apply_outbound_message_guard,
    set_outbound_message_guard,
)


def _model() -> ChatLiteLLM:
    return ChatLiteLLM.model_construct(client=MagicMock(), model="gpt-5-chat")


@pytest.fixture(autouse=True)
def _no_guard() -> Iterator[None]:
    set_outbound_message_guard(None)
    yield
    set_outbound_message_guard(None)


def test_without_a_guard_the_wire_messages_are_untouched() -> None:
    message_dicts, _ = _model()._create_message_dicts([HumanMessage(content="call 13812345678")], stop=None)
    assert message_dicts == [{"role": "user", "content": "call 13812345678"}]


def test_guard_sees_the_final_wire_messages_and_its_rewrite_is_what_gets_sent() -> None:
    seen: list[list[dict[str, object]]] = []

    def guard(message_dicts: list[dict[str, object]]) -> None:
        seen.append([dict(m) for m in message_dicts])
        for message in message_dicts:
            if message.get("role") == "user":
                message["content"] = "[masked]"

    set_outbound_message_guard(guard)
    message_dicts, _ = _model()._create_message_dicts(
        [SystemMessage(content="be brief"), HumanMessage(content="call 13812345678"), AIMessage(content="ok")],
        stop=None,
    )

    # gpt-5 models take the instruction as a developer message: the guard sees the wire form, not the LangChain one.
    assert [m["role"] for m in seen[0]] == ["developer", "user", "assistant"]
    assert message_dicts[1]["content"] == "[masked]"
    assert message_dicts[0]["content"] == "be brief"


def test_a_failing_guard_stops_the_call_instead_of_sending_unguarded_text() -> None:
    def guard(message_dicts: list[dict[str, object]]) -> None:
        raise RuntimeError("guard broke")

    set_outbound_message_guard(guard)
    with pytest.raises(RuntimeError, match="guard broke"):
        _model()._create_message_dicts([HumanMessage(content="call 13812345678")], stop=None)


def test_registering_none_removes_the_guard() -> None:
    calls: list[int] = []
    set_outbound_message_guard(lambda message_dicts: calls.append(len(message_dicts)))
    set_outbound_message_guard(None)
    apply_outbound_message_guard([{"role": "user", "content": "x"}])
    assert calls == []


def _response() -> dict[str, object]:
    return {
        "id": "chatcmpl-1",
        "model": "test-model",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _mask_user_messages(message_dicts: list[dict[str, object]]) -> None:
    for message in message_dicts:
        if message.get("role") == "user":
            message["content"] = "[masked]"


def test_a_sync_request_reaches_the_provider_only_through_the_guard() -> None:
    set_outbound_message_guard(_mask_user_messages)
    model = ChatLiteLLM(model="openai/test-model")
    model.client = MagicMock()
    model.client.completion.return_value = _response()

    model.invoke([HumanMessage(content="call 13812345678")])

    sent = model.client.completion.call_args.kwargs["messages"]
    assert [m["content"] for m in sent] == ["[masked]"]


@pytest.mark.asyncio
async def test_an_async_request_reaches_the_provider_only_through_the_guard() -> None:
    set_outbound_message_guard(_mask_user_messages)
    model = ChatLiteLLM(model="openai/test-model")
    model.client = MagicMock()
    model.client.acreate = AsyncMock(return_value=_response())

    await model.ainvoke([HumanMessage(content="call 13812345678")])

    sent = model.client.acreate.call_args.kwargs["messages"]
    assert [m["content"] for m in sent] == ["[masked]"]


def test_the_message_mixin_is_the_only_place_that_builds_wire_messages() -> None:
    """The guard hangs on ``_create_message_dicts``; a second builder would send text past it."""
    package = Path(__file__).resolve().parents[4] / "src/myrm_agent_harness/toolkits/llms/adapters/chat_model"
    builders = sorted(
        path.name for path in package.glob("*.py") if "convert_message_to_dict(" in path.read_text(encoding="utf-8")
    )
    assert builders == ["message_mixin.py"]

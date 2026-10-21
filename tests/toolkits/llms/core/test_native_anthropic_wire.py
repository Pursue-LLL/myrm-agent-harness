"""Wire-level proof that a native Anthropic call carries what the Messages API accepts and nothing else.

The Messages API rejects unknown top-level fields. Each test builds the LLM through the production factory,
makes one real LiteLLM call against a strict loopback fake of that API and inspects what arrived there:
a request the fake refuses surfaces as a failed call or as a second request, because the adapter's
reactive parameter stripping would otherwise hide the problem behind retries.
"""

from __future__ import annotations

from collections.abc import Iterator

import litellm
import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from myrm_agent_harness.toolkits.llms.core.llm import ChatLiteLLM, create_litellm_model
from tests.mocks.llm_wire_server import (
    ANTHROPIC_REQUEST_FIELDS,
    FakeProviderServer,
    FakeReply,
    JsonBody,
    anthropic_text_stream,
    openai_text_stream,
    strict_anthropic_responder,
)

CLAUDE = "anthropic/claude-sonnet-4-20250514"
OPENAI_REASONING = "openai/gpt-5-mini"


@pytest.fixture(autouse=True)
def _production_litellm_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apply the global LiteLLM switches the harness sets in production and keep the loopback off any proxy."""
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setattr(litellm, "drop_params", True)
    monkeypatch.setattr(litellm, "modify_params", True)
    monkeypatch.setattr(litellm, "cache", None)


@pytest.fixture
def usages(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[object]]:
    """Usage objects the adapter hands to the token ledger."""
    recorded: list[object] = []
    original = ChatLiteLLM._record_usage

    def spy(self: ChatLiteLLM, usage: object, **kwargs: object) -> None:
        recorded.append(usage)
        original(self, usage, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ChatLiteLLM, "_record_usage", spy)
    yield recorded


@tool
def read_file(path: str) -> str:
    """Read a file."""
    return path


def _strict_server() -> FakeProviderServer:
    return FakeProviderServer(strict_anthropic_responder(anthropic_text_stream("hello")))


def _unknown_fields(body: JsonBody) -> list[str]:
    return sorted(set(body) - ANTHROPIC_REQUEST_FIELDS)


async def _claude_requests(**kwargs: object) -> list[JsonBody]:
    with _strict_server() as server:
        llm = create_litellm_model(CLAUDE, base_url=server.base_url, api_key="sk-offline", streaming=True, **kwargs)
        await llm.ainvoke([HumanMessage(content="hello")])
    return server.requests


async def test_plain_call_takes_one_request_with_only_messages_api_fields() -> None:
    requests = await _claude_requests(max_tokens=1024)

    assert len(requests) == 1
    assert _unknown_fields(requests[0]) == []


async def test_stream_usage_still_reaches_the_ledger(usages: list[object]) -> None:
    await _claude_requests(max_tokens=1024)

    assert [(u.prompt_tokens, u.completion_tokens) for u in usages] == [(3, 9)]  # type: ignore[attr-defined]


async def test_reasoning_effort_is_translated_into_thinking() -> None:
    requests = await _claude_requests(max_tokens=1024, reasoning_effort="low")

    assert len(requests) == 1
    assert requests[0]["thinking"]["type"] == "enabled"
    assert _unknown_fields(requests[0]) == []


async def test_tool_call_takes_one_request_and_keeps_the_parallelism_choice() -> None:
    with _strict_server() as server:
        llm = create_litellm_model(
            CLAUDE, base_url=server.base_url, api_key="sk-offline", streaming=True, max_tokens=1024
        )
        bound = llm.bind_tools([read_file], tool_choice="auto", parallel_tool_calls=True)
        await bound.ainvoke([HumanMessage(content="hello")])

    assert len(server.requests) == 1
    assert _unknown_fields(server.requests[0]) == []
    assert server.requests[0]["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": False}


async def test_openai_shaped_call_kwargs_are_translated_not_duplicated() -> None:
    with _strict_server() as server:
        llm = create_litellm_model(
            CLAUDE, base_url=server.base_url, api_key="sk-offline", streaming=True, max_tokens=1024
        )
        await llm.ainvoke([HumanMessage(content="hello")], stop=["END"], user="user-1")

    assert len(server.requests) == 1
    assert _unknown_fields(server.requests[0]) == []
    assert server.requests[0]["stop_sequences"] == ["END"]
    assert server.requests[0]["metadata"] == {"user_id": "user-1"}


async def test_extra_model_kwargs_never_become_a_literal_extra_body() -> None:
    requests = await _claude_requests(max_tokens=1024, temperature=0.2, top_k=5)

    assert len(requests) == 1
    assert "extra_body" not in requests[0]
    assert requests[0]["temperature"] == 0.2


async def test_micro_call_guard_keeps_a_small_cap_and_no_thinking() -> None:
    requests = await _claude_requests(max_tokens=30, supports_reasoning=False)

    assert len(requests) == 1
    assert requests[0]["max_tokens"] == 30
    assert "thinking" not in requests[0]
    assert _unknown_fields(requests[0]) == []


async def test_openai_wire_keeps_its_forwarding_behaviour() -> None:
    """The exemption is Anthropic-only: other providers still get stream usage, the effort level and mirrored extras."""
    with FakeProviderServer(lambda _body: FakeReply(openai_text_stream())) as server:
        llm = create_litellm_model(
            OPENAI_REASONING,
            base_url=f"{server.base_url}/v1",
            api_key="sk-offline",
            streaming=True,
            max_tokens=64,
            reasoning_effort="low",
            top_k=5,
        )
        await llm.ainvoke([HumanMessage(content="hello")])

    body = server.requests[0]
    assert body["stream_options"] == {"include_usage": True}
    assert body["reasoning_effort"] == "low"
    assert body["top_k"] == 5

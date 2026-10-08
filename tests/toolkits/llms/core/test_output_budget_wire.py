"""Wire-level proof that the output budget the adapter computes is the budget the provider receives.

Each test builds the LLM through the production factory, makes one real LiteLLM call against a loopback
provider and inspects the request body that arrived there. Asserting on the wire (not on the constructed
object) is the point: a value that is correct on the Python side but overridden on the way out is invisible
to unit tests.
"""

from __future__ import annotations

import litellm
import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.toolkits.llms.core.llm import create_litellm_model
from myrm_agent_harness.toolkits.llms.ephemeral_output_tokens import (
    reset_ephemeral_max_output_tokens,
    set_ephemeral_max_output_tokens,
)
from tests.mocks.llm_wire_server import FakeProviderServer, FakeReply, JsonBody, openai_text_stream

THINKING_MODEL = "openai/minimax-m3"  # matches the reasoning catalog: headroom floor 16384 without an effort level
PLAIN_MODEL = "openai/plain-chat-model"


@pytest.fixture(autouse=True)
def _production_litellm_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apply the global LiteLLM switches the harness sets in production and keep the loopback off any proxy."""
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setattr(litellm, "drop_params", True)
    monkeypatch.setattr(litellm, "modify_params", True)
    monkeypatch.setattr(litellm, "cache", None)


async def _request_body(model: str, **kwargs: object) -> JsonBody:
    """Make one call through the production factory and return the body the provider received."""
    with FakeProviderServer(lambda _body: FakeReply(openai_text_stream())) as server:
        llm = create_litellm_model(
            model,
            base_url=f"{server.base_url}/v1",
            api_key="sk-offline",
            streaming=True,
            **kwargs,
        )
        await llm.ainvoke([HumanMessage(content="hello")])
    assert len(server.requests) == 1
    return server.requests[0]


async def test_configured_cap_below_thinking_floor_reaches_the_wire_as_the_floor() -> None:
    body = await _request_body(THINKING_MODEL, max_tokens=1024)

    assert body["max_tokens"] == 16384


async def test_cap_of_a_non_thinking_model_is_honoured() -> None:
    body = await _request_body(PLAIN_MODEL, max_tokens=1024)

    assert body["max_tokens"] == 1024


async def test_cap_above_the_floor_is_never_lowered() -> None:
    body = await _request_body(THINKING_MODEL, max_tokens=40000)

    assert body["max_tokens"] == 40000


async def test_micro_call_guard_keeps_a_small_cap_and_a_clean_body() -> None:
    body = await _request_body(THINKING_MODEL, max_tokens=30, supports_reasoning=False)

    assert body["max_tokens"] == 30
    assert "supports_reasoning" not in body


async def test_truncation_recovery_boost_reaches_the_wire() -> None:
    set_ephemeral_max_output_tokens(4096)
    try:
        body = await _request_body(PLAIN_MODEL, max_tokens=1024)
    finally:
        reset_ephemeral_max_output_tokens()

    assert body["max_tokens"] == 4096


async def test_caller_extra_body_is_sent_once_without_a_self_reference() -> None:
    body = await _request_body(PLAIN_MODEL, max_tokens=64, extra_body={"custom_flag": "on"}, top_p=0.5)

    assert body["custom_flag"] == "on"
    assert body["top_p"] == 0.5
    assert "extra_body" not in body

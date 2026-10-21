"""Wire-level proof that a stream the connection cut short never executes a half-written tool call.

LiteLLM's stream wrapper answers a stream that ended without any provider finish marker with a synthesized
``stop``. Each test drives the real adapter -> LiteLLM -> HTTP path against a loopback fake provider that
either finishes properly or closes the connection mid-call, and inspects the message the agent would act on.
"""

from __future__ import annotations

import litellm
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from myrm_agent_harness.toolkits.llms.adapters.tool_recovery import has_withheld_tool_calls
from myrm_agent_harness.toolkits.llms.core.llm import create_litellm_model
from tests.mocks.llm_wire_server import (
    FakeProviderServer,
    FakeReply,
    anthropic_text_stream,
    anthropic_tool_stream,
    openai_text_stream,
    openai_tool_stream,
)

OPENAI_MODEL = "openai/gpt-4o-mini"
ANTHROPIC_MODEL = "anthropic/claude-sonnet-4-20250514"

FINISHED_ARGS = ['{"path": "/tmp/report.md", ', '"content": "Dear Alice.", "overwrite": true}']
# Cut between two values: closing the prefix gives a valid object that silently lacks "overwrite".
CUT_AT_BOUNDARY = ['{"path": "/tmp/report.md", ', '"content": "Dear Alice.", ']
CUT_INSIDE_VALUE = ['{"path": "/tmp/report.md", ', '"content": "Dear Alice, the figures are']


@pytest.fixture(autouse=True)
def _production_litellm_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apply the global LiteLLM switches the harness sets in production and keep the loopback off any proxy."""
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setattr(litellm, "drop_params", True)
    monkeypatch.setattr(litellm, "modify_params", True)
    monkeypatch.setattr(litellm, "cache", None)


@tool
def write_file(path: str, content: str, overwrite: bool = False) -> str:
    """Write a file."""
    return path


async def _answer(model: str, stream: bytes) -> AIMessage:
    base_path = "/v1" if model == OPENAI_MODEL else ""
    with FakeProviderServer(lambda _body: FakeReply(stream)) as server:
        llm = create_litellm_model(
            model, base_url=server.base_url + base_path, api_key="sk-offline", streaming=True, max_tokens=1024
        )
        return await llm.bind_tools([write_file]).ainvoke([HumanMessage(content="save the report")])  # type: ignore[return-value]


def _cut_streams(pieces: list[str]) -> dict[str, tuple[str, bytes]]:
    return {
        "openai": (OPENAI_MODEL, openai_tool_stream("write_file", pieces, finish=None, send_done=False)),
        "anthropic-open-block": (
            ANTHROPIC_MODEL,
            anthropic_tool_stream("write_file", pieces, stop_reason=None, close_block=False),
        ),
        "anthropic-closed-block": (ANTHROPIC_MODEL, anthropic_tool_stream("write_file", pieces, stop_reason=None)),
    }


CUT_TOOL_STREAMS = _cut_streams(CUT_AT_BOUNDARY)
CUT_INSIDE_VALUE_STREAMS = _cut_streams(CUT_INSIDE_VALUE)

FINISHED_TOOL_STREAMS = {
    "openai": (OPENAI_MODEL, openai_tool_stream("write_file", FINISHED_ARGS)),
    "anthropic": (ANTHROPIC_MODEL, anthropic_tool_stream("write_file", FINISHED_ARGS)),
}


@pytest.mark.parametrize(("model", "stream"), CUT_TOOL_STREAMS.values(), ids=CUT_TOOL_STREAMS.keys())
async def test_cut_tool_call_is_withheld_not_repaired_and_run(model: str, stream: bytes) -> None:
    message = await _answer(model, stream)

    assert message.tool_calls == []
    assert has_withheld_tool_calls(message.additional_kwargs)


@pytest.mark.parametrize(("model", "stream"), CUT_INSIDE_VALUE_STREAMS.values(), ids=CUT_INSIDE_VALUE_STREAMS.keys())
async def test_call_cut_inside_a_value_is_withheld(model: str, stream: bytes) -> None:
    message = await _answer(model, stream)

    assert message.tool_calls == []
    assert has_withheld_tool_calls(message.additional_kwargs)


@pytest.mark.parametrize(("model", "stream"), FINISHED_TOOL_STREAMS.values(), ids=FINISHED_TOOL_STREAMS.keys())
async def test_finished_tool_call_still_runs(model: str, stream: bytes) -> None:
    message = await _answer(model, stream)

    assert [call["args"] for call in message.tool_calls] == [
        {"path": "/tmp/report.md", "content": "Dear Alice.", "overwrite": True}
    ]
    assert not has_withheld_tool_calls(message.additional_kwargs)


@pytest.mark.parametrize(
    ("model", "stream"),
    [
        (OPENAI_MODEL, openai_text_stream("The figures are", finish=None, send_done=False)),
        (ANTHROPIC_MODEL, anthropic_text_stream("The figures are", stop_reason=None)),
    ],
    ids=["openai", "anthropic"],
)
async def test_cut_text_answer_keeps_what_arrived(model: str, stream: bytes) -> None:
    message = await _answer(model, stream)

    assert message.content == "The figures are"
    assert message.tool_calls == []
    assert not has_withheld_tool_calls(message.additional_kwargs)

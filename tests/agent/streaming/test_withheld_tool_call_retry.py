"""A tool call withheld as unsafe must end in a retry or a report, never in silence.

Argument text that is cut off or unparseable is never executed: the adapter records it
in ``additional_kwargs["tool_call_recovery"]`` and emits no ``tool_calls``. LangGraph
ends a turn whose last AI message has no tool calls, so these tests drive the real
``create_agent`` loop through ``StreamExecutor.execute()`` to prove recovery sees that
message, retries once with a larger output budget, and stays bounded.
"""

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool, tool
from langgraph.types import Command
from pydantic import ConfigDict, Field

from myrm_agent_harness.agent.middlewares.tooling.dangling_tool_call_middleware import dangling_tool_call_middleware
from myrm_agent_harness.agent.streaming.event_handlers import process_updates_chunk
from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor
from myrm_agent_harness.agent.types import AgentRunStatistics
from myrm_agent_harness.toolkits.llms.adapters.tool_recovery import build_final_tool_call_chunk
from myrm_agent_harness.toolkits.llms.ephemeral_output_tokens import (
    get_ephemeral_max_output_tokens,
    reset_ephemeral_max_output_tokens,
)
from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

BASE_MAX_TOKENS = 1_000
FULL_REPORT = "# Q3 report\n\nRevenue grew by 12%.\n"
# ``content`` is cut inside its string value, as an output-length limit does.
CUT_ARGUMENTS = '{"path": "report.md", "content": "# Q3 report\\n\\nRevenue grew by 1'
TRACKER_PATH = "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker"

Turn = tuple[AIMessage, str]
"""One scripted model generation: the final AI message and the provider's finish_reason."""


@pytest.fixture(autouse=True)
def _isolated_output_budget():
    reset_ephemeral_max_output_tokens()
    yield
    reset_ephemeral_max_output_tokens()


# ---------------------------------------------------------------------------
# Scripted model and executor harness
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    """What one model call received."""

    max_tokens: int
    messages: tuple[tuple[str, str], ...]  # (message class name, content)


class ScriptedModel(BaseChatModel):
    """Plays one scripted turn per call; an unscripted extra call fails the test loudly."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    turns: list[Turn]
    tracker: MagicMock
    requests: list[Request] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: object, **kwargs: object) -> "ScriptedModel":
        return self

    def _respond(self, messages: list[BaseMessage]) -> ChatResult:
        call_number = len(self.requests) + 1
        self.requests.append(
            Request(
                max_tokens=get_ephemeral_max_output_tokens() or BASE_MAX_TOKENS,
                messages=tuple((type(m).__name__, str(m.content)) for m in messages),
            )
        )
        if call_number > len(self.turns):
            raise AssertionError(f"unscripted model call #{call_number}")
        message, finish_reason = self.turns[call_number - 1]
        # The real adapter records the provider's finish_reason on the token tracker.
        self.tracker.last_finish_reason = finish_reason
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _generate(
        self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: object = None, **kwargs: object
    ) -> ChatResult:
        return self._respond(messages)

    async def _agenerate(
        self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: object = None, **kwargs: object
    ) -> ChatResult:
        return self._respond(messages)


class RecordingCompactor:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def put(self, event: object) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        pass

    @property
    def status_events(self) -> list[dict[str, object]]:
        return [event for event in self.events if isinstance(event, dict) and event.get("step_key")]

    @property
    def steps(self) -> list[str]:
        return [str(event["step_key"]) for event in self.status_events]


@dataclass
class Run:
    requests: list[Request]
    executed: list[tuple[str, str]]
    compactor: RecordingCompactor
    error: Exception | None

    @property
    def truncation_steps(self) -> list[str]:
        return [step for step in self.compactor.steps if step in ("tool_call_retry", "tool_call_truncated")]


def _adapter_message(raw_calls: list[dict[str, object]], *, stream_complete: bool | None) -> AIMessage:
    """The final message the chat adapter builds for ``raw_calls`` (withheld calls only in metadata)."""
    chunk, _, _ = build_final_tool_call_chunk(raw_calls, None, stream_complete=stream_complete)
    assert chunk is not None
    return AIMessage(
        content="",
        tool_calls=list(chunk.message.tool_calls),
        additional_kwargs=dict(chunk.message.additional_kwargs),
    )


def _raw_write(call_id: str, arguments: str) -> dict[str, object]:
    return {"id": call_id, "type": "function", "function": {"name": "write_file", "arguments": arguments}}


def _withheld_message(arguments: str = CUT_ARGUMENTS, *, stream_complete: bool | None = False) -> AIMessage:
    message = _adapter_message([_raw_write("call_cut", arguments)], stream_complete=stream_complete)
    assert message.tool_calls == []
    return message


def _complete_write() -> Turn:
    call = {"name": "write_file", "args": {"path": "report.md", "content": FULL_REPORT}, "id": "call_ok"}
    return AIMessage(content="", tool_calls=[call]), "tool_calls"


def _final_answer() -> Turn:
    return AIMessage(content="Done: report.md written."), "stop"


def _context(agent: object, agent_input: object) -> StreamContext:
    ctx = StreamContext(
        agent=agent,
        agent_input=agent_input,
        merged_context={"locale": "en"},
        run_config={"recursion_limit": 12},
        stats=AgentRunStatistics(),
        message_id="msg",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
    )
    ctx.llm = MagicMock(max_tokens=BASE_MAX_TOKENS, model_kwargs={}, model_name="scripted-model")
    return ctx


def _executor(ctx: StreamContext) -> StreamExecutor:
    executor = StreamExecutor(ctx=ctx, fallback_llm=None, safety_fallback_llm=None, rebuild_agent_fn=MagicMock())
    executor._compactor = RecordingCompactor()
    return executor


async def _run_agent(turns: list[Turn]) -> tuple[Run, ScriptedModel]:
    """Run the real agent loop and executor against the scripted turns."""
    executed: list[tuple[str, str]] = []

    @tool
    def write_file(path: str, content: str) -> str:
        """Write a file."""
        executed.append((path, content))
        return f"wrote {path}"

    tracker = MagicMock(last_finish_reason=None, usage=None, total_cost_usd=0.0)
    model = ScriptedModel(turns=turns, tracker=tracker)
    tools: list[BaseTool] = [write_file]
    agent = create_agent(model=model, tools=tools, middleware=[dangling_tool_call_middleware])
    executor = _executor(_context(agent, {"messages": [HumanMessage(content="Write the Q3 report to report.md")]}))

    error: Exception | None = None
    with (
        patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock),
        patch(TRACKER_PATH, return_value=tracker),
    ):
        try:
            await executor.execute()
        except Exception as exc:
            error = exc
    compactor = executor._compactor
    assert isinstance(compactor, RecordingCompactor)
    return Run(requests=model.requests, executed=executed, compactor=compactor, error=error), model


# ---------------------------------------------------------------------------
# Real agent loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_path_is_untouched():
    run, _ = await _run_agent([_complete_write(), _final_answer()])

    assert run.error is None
    assert run.executed == [("report.md", FULL_REPORT)]
    assert run.truncation_steps == []
    assert [request.max_tokens for request in run.requests] == [BASE_MAX_TOKENS] * 2


@pytest.mark.asyncio
async def test_output_cut_inside_a_call_is_retried_once_with_a_larger_budget():
    cut = (_withheld_message(), "length")

    run, _ = await _run_agent([cut, _complete_write(), _final_answer()])

    assert run.error is None
    assert run.executed == [("report.md", FULL_REPORT)]  # the cut file body was never written
    assert [request.max_tokens for request in run.requests[:2]] == [BASE_MAX_TOKENS, 2 * BASE_MAX_TOKENS]
    assert run.truncation_steps == ["tool_call_retry"]
    retry_event = next(event for event in run.compactor.status_events if event["step_key"] == "tool_call_retry")
    assert retry_event["restart"] is True


@pytest.mark.asyncio
async def test_retry_request_extends_the_first_request_by_exactly_one_hint():
    """Prompt-cache invariant: the retry re-sends the original prefix byte for byte and only appends."""
    run, _ = await _run_agent([(_withheld_message(), "length"), _complete_write(), _final_answer()])

    first, retry = run.requests[0], run.requests[1]
    assert retry.messages[: len(first.messages)] == first.messages
    assert len(retry.messages) == len(first.messages) + 1
    role, hint = retry.messages[-1]
    assert role == "HumanMessage"
    assert "not executed" in hint
    assert "retry" in hint.lower()


@pytest.mark.asyncio
async def test_provider_reporting_a_normal_finish_is_still_recovered():
    """The cut is detected from the arguments themselves, not from the provider's finish_reason."""
    lying = (_withheld_message(stream_complete=True), "tool_calls")

    run, _ = await _run_agent([lying, _complete_write(), _final_answer()])

    assert run.error is None
    assert run.executed == [("report.md", FULL_REPORT)]
    assert run.truncation_steps == ["tool_call_retry"]


@pytest.mark.asyncio
async def test_unparseable_arguments_are_retried():
    garbage = (_withheld_message("{{{ this is not json at all", stream_complete=None), "tool_calls")

    run, _ = await _run_agent([garbage, _complete_write(), _final_answer()])

    assert run.error is None
    assert run.executed == [("report.md", FULL_REPORT)]
    assert run.truncation_steps == ["tool_call_retry"]


@pytest.mark.asyncio
async def test_hopeless_truncation_is_bounded_and_reported():
    cut = (_withheld_message(), "length")

    run, model = await _run_agent([cut, cut])

    assert run.error is None  # a third (unscripted) model call would have surfaced as an error
    assert len(model.requests) == 2
    assert run.executed == []
    assert run.truncation_steps == ["tool_call_retry", "tool_call_truncated"]


@pytest.mark.asyncio
async def test_complete_calls_next_to_a_withheld_one_still_run_and_the_model_is_told():
    two_calls = [
        _raw_write("call_a", '{"path": "notes.md", "content": "short note"}'),
        _raw_write("call_b", CUT_ARGUMENTS),
    ]
    mixed = (_adapter_message(two_calls, stream_complete=False), "length")

    run, _ = await _run_agent([mixed, _final_answer()])

    assert run.error is None
    assert run.executed == [("notes.md", "short note")]
    assert run.truncation_steps == []  # the turn went on, so the model itself sees the failed call
    tool_reports = [content for role, content in run.requests[1].messages if role == "ToolMessage"]
    assert any("arguments were invalid" in report for report in tool_reports)


# ---------------------------------------------------------------------------
# Handlers in isolation
# ---------------------------------------------------------------------------


def _handler_executor(agent_input: object) -> StreamExecutor:
    return _executor(_context(None, agent_input))


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["length", "max_tokens", "tool_calls", "stop", None])
async def test_withheld_call_triggers_a_retry_whatever_the_provider_reports(finish_reason: str | None):
    executor = _handler_executor({"messages": []})

    with patch(TRACKER_PATH, return_value=MagicMock(last_finish_reason=finish_reason)):
        retried = await executor._handle_length_truncation([_withheld_message()])

    assert retried is True
    assert executor._tool_truncation_retries == 1
    assert executor._compactor.steps == ["tool_call_retry"]


@pytest.mark.asyncio
async def test_repaired_call_without_a_length_cut_is_not_retried():
    repaired = AIMessage(
        content="",
        additional_kwargs={
            "tool_call_recovery": [{"tool_call_id": "call_1", "strategy": "truncated_completion", "safe": True}]
        },
    )
    executor = _handler_executor({"messages": []})

    with patch(TRACKER_PATH, return_value=MagicMock(last_finish_reason="stop")):
        retried = await executor._handle_length_truncation([repaired])

    assert retried is False
    assert executor._compactor.events == []


@pytest.mark.asyncio
async def test_exhausted_retry_reports_instead_of_looping():
    executor = _handler_executor({"messages": []})
    executor._tool_truncation_retries = executor._MAX_TOOL_TRUNCATION_RETRIES

    with patch(TRACKER_PATH, return_value=MagicMock(last_finish_reason="stop")):
        retried = await executor._handle_length_truncation([_withheld_message()])

    assert retried is False
    assert executor._compactor.steps == ["tool_call_truncated"]


@pytest.mark.asyncio
async def test_resumed_turn_reports_instead_of_retrying():
    """A consumed ``Command`` cannot be replayed, so the retry would advance no work."""
    executor = _handler_executor(Command(resume="approved"))

    with patch(TRACKER_PATH, return_value=MagicMock(last_finish_reason="stop")):
        retried = await executor._handle_length_truncation([_withheld_message()])

    assert retried is False
    assert executor._tool_truncation_retries == 0
    assert executor._compactor.steps == ["tool_call_truncated"]


@pytest.mark.asyncio
async def test_withheld_call_is_not_mistaken_for_an_empty_response():
    """Otherwise empty-response recovery would stack on top and finally raise ``MyrmLLMError``."""
    executor = _handler_executor({"messages": []})

    assert await executor._handle_empty_response([_withheld_message()], retries=5) is False
    with pytest.raises(MyrmLLMError):
        await executor._handle_empty_response([AIMessage(content="")], retries=5)


async def _collect_from_updates(messages: list[BaseMessage]) -> list[BaseMessage]:
    collected: list[BaseMessage] = []
    updates: dict[str, dict[str, object]] = {"model": {"messages": messages}}
    async for _ in process_updates_chunk(updates, AgentRunStatistics(), "msg", collected_messages=collected):
        pass
    return collected


@pytest.mark.asyncio
async def test_update_stream_keeps_a_message_that_only_records_a_withheld_call():
    withheld = _withheld_message()

    assert await _collect_from_updates([withheld]) == [withheld]


@pytest.mark.asyncio
async def test_update_stream_still_drops_a_truly_empty_ai_message():
    assert await _collect_from_updates([AIMessage(content="")]) == []


@pytest.mark.asyncio
async def test_update_stream_keeps_tool_results_in_order():
    result = ToolMessage(content="wrote report.md", tool_call_id="call_ok", name="write_file")
    answer = AIMessage(content="Done")

    assert await _collect_from_updates([result, answer]) == [result, answer]

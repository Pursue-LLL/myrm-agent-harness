from __future__ import annotations

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.runtime import Runtime
from pydantic import Field

from myrm_agent_harness.agent.middlewares.security.security_boundary_middleware import SecurityBoundaryMiddleware
from myrm_agent_harness.agent.security.detection.content_boundary import SECURITY_BOUNDARY_SYSTEM_RULES


def test_security_boundary_middleware_no_system_message():
    middleware = SecurityBoundaryMiddleware()
    state = {"messages": [HumanMessage(content="hello")]}

    result = middleware.before_model(state, None)

    assert result is not None
    messages = result["messages"]
    assert len(messages) == 1
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == SECURITY_BOUNDARY_SYSTEM_RULES


def test_security_boundary_middleware_with_system_message():
    middleware = SecurityBoundaryMiddleware()
    state = {"messages": [SystemMessage(content="You are a helpful assistant."), HumanMessage(content="hello")]}

    result = middleware.before_model(state, None)

    assert result is not None
    messages = result["messages"]
    assert len(messages) == 1
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == SECURITY_BOUNDARY_SYSTEM_RULES


def test_security_boundary_middleware_idempotent():
    middleware = SecurityBoundaryMiddleware()
    state = {
        "messages": [
            SystemMessage(content="You are a helpful assistant."),
            SystemMessage(content=SECURITY_BOUNDARY_SYSTEM_RULES),
            HumanMessage(content="hello"),
        ]
    }

    result = middleware.before_model(state, None)

    # Should return None because it's already injected
    assert result is None


def test_security_boundary_middleware_empty_messages():
    middleware = SecurityBoundaryMiddleware()
    state = {"messages": []}

    result = middleware.before_model(state, None)

    assert result is None


def test_security_boundary_middleware_after_model_noop():
    middleware = SecurityBoundaryMiddleware()
    state = {"messages": [HumanMessage(content="hello")]}

    result = middleware.after_model(state, None)

    assert result is None


def test_security_boundary_middleware_global_idempotency_prevents_duplicate():
    """Validates that if messages[0] already contains boundary rules, it will not duplicate."""
    middleware = SecurityBoundaryMiddleware()
    state = {
        "messages": [
            SystemMessage(content=f"{SECURITY_BOUNDARY_SYSTEM_RULES}\n<tool_guidance>foo</tool_guidance>"),
            HumanMessage(content="hello"),
        ]
    }

    result = middleware.before_model(state, None)
    assert result is None


@tool
def ping() -> str:
    """Answer pong."""
    return "pong"


class _RecordingModel(BaseChatModel):
    """Calls the tool once, then answers; records what each call was sent as (type, boundary rules?) pairs."""

    calls: list[list[tuple[str, bool]]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "recording"

    def bind_tools(self, tools: object, **kwargs: object) -> _RecordingModel:
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: object = None, **kwargs: object
    ) -> ChatResult:
        self.calls.append([(type(m).__name__, "<data_boundary_rules" in str(m.content)) for m in messages])
        first = len(self.calls) == 1
        reply = (
            AIMessage(content="", tool_calls=[{"id": "call-1", "name": "ping", "args": {}}])
            if first
            else AIMessage(content="done")
        )
        return ChatResult(generations=[ChatGeneration(message=reply)])


class _StateReader(AgentMiddleware):
    """Sits behind the boundary middleware and reads the message list the way later middlewares do."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[list[str]] = []

    def before_model(self, state: AgentState, runtime: Runtime) -> None:
        self.seen.append([type(m).__name__ for m in state["messages"]])


def test_the_rules_follow_the_input_and_stay_in_place_across_a_tool_loop():
    """In a real graph the message list is merged by appending, so the rules land behind the input, once."""
    model = _RecordingModel()
    reader = _StateReader()
    agent = create_agent(model, tools=[ping], middleware=[SecurityBoundaryMiddleware(), reader])

    agent.invoke({"messages": [SystemMessage(content="core prompt"), HumanMessage(content="hello")]})

    first, second = model.calls
    assert first == [("SystemMessage", False), ("HumanMessage", False), ("SystemMessage", True)]
    assert second == [*first, ("AIMessage", False), ("ToolMessage", False)]
    assert reader.seen[0] == ["SystemMessage", "HumanMessage", "SystemMessage"]

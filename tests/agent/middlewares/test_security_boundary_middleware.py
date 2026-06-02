from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.middlewares.security_boundary_middleware import SecurityBoundaryMiddleware
from myrm_agent_harness.agent.security.detection.content_boundary import SECURITY_BOUNDARY_SYSTEM_RULES


def test_security_boundary_middleware_no_system_message():
    middleware = SecurityBoundaryMiddleware()
    state = {"messages": [HumanMessage(content="hello")]}

    result = middleware.before_model(state, None)

    assert result is not None
    messages = result["messages"]
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == SECURITY_BOUNDARY_SYSTEM_RULES
    assert isinstance(messages[1], HumanMessage)


def test_security_boundary_middleware_with_system_message():
    middleware = SecurityBoundaryMiddleware()
    state = {"messages": [SystemMessage(content="You are a helpful assistant."), HumanMessage(content="hello")]}

    result = middleware.before_model(state, None)

    assert result is not None
    messages = result["messages"]
    assert len(messages) == 3
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == "You are a helpful assistant."
    assert isinstance(messages[1], SystemMessage)
    assert messages[1].content == SECURITY_BOUNDARY_SYSTEM_RULES
    assert isinstance(messages[2], HumanMessage)


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

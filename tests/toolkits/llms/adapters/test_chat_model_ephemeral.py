from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM


@pytest.fixture
def chat_model():
    model = ChatLiteLLM(model="test-model")
    model.client = MagicMock()
    return model


@pytest.fixture
def messages():
    return [HumanMessage(content="test message")]


# ---------------------------------------------------------------------------
# _apply_ephemeral_output_override unit tests
# ---------------------------------------------------------------------------


def test_apply_ephemeral_override_sets_max_tokens():
    """When ContextVar is set, _apply_ephemeral_output_override applies it and resets."""
    from myrm_agent_harness.agent.streaming.stream_recovery_truncation import (
        get_ephemeral_max_output_tokens,
        set_ephemeral_max_output_tokens,
    )

    set_ephemeral_max_output_tokens(16000)
    params: dict[str, object] = {"max_tokens": 4000}

    ChatLiteLLM._apply_ephemeral_output_override(params)

    assert params["max_tokens"] == 16000
    assert get_ephemeral_max_output_tokens() is None


def test_apply_ephemeral_override_noop_when_unset():
    """When ContextVar is None, _apply_ephemeral_output_override is a no-op."""
    from myrm_agent_harness.agent.streaming.stream_recovery_truncation import (
        reset_ephemeral_max_output_tokens,
    )

    reset_ephemeral_max_output_tokens()
    params: dict[str, object] = {"max_tokens": 4000}

    ChatLiteLLM._apply_ephemeral_output_override(params)

    assert params["max_tokens"] == 4000


def test_sync_ephemeral_output_cap_fast_fail(chat_model, messages, monkeypatch):
    error = Exception("context overflow")
    monkeypatch.setattr("myrm_agent_harness.toolkits.llms.errors.classifier.is_context_overflow", lambda e: True)
    monkeypatch.setattr("myrm_agent_harness.toolkits.llms.errors.classifier.parse_available_output_tokens_from_error", lambda e: 400)

    chat_model.client.completion.side_effect = error

    with pytest.raises(Exception, match="context overflow"):
        chat_model._generate(messages)

    # Should only be called once because it fast-fails
    assert chat_model.client.completion.call_count == 1

def test_sync_ephemeral_output_cap_retry(chat_model, messages, monkeypatch):
    error = Exception("context overflow")
    monkeypatch.setattr("myrm_agent_harness.toolkits.llms.errors.classifier.is_context_overflow", lambda e: True)
    monkeypatch.setattr("myrm_agent_harness.toolkits.llms.errors.classifier.parse_available_output_tokens_from_error", lambda e: 600)

    # First call fails with context overflow, second succeeds
    mock_response = {
        "choices": [{"message": {"role": "assistant", "content": "success"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }

    chat_model.client.completion.side_effect = [error, mock_response]

    result = chat_model._generate(messages)

    # Should be called twice (one failure, one success)
    assert chat_model.client.completion.call_count == 2
    assert result.generations[0].message.content == "success"

async def test_async_ephemeral_output_cap_fast_fail(chat_model, messages, monkeypatch):
    error = Exception("context overflow")
    monkeypatch.setattr("myrm_agent_harness.toolkits.llms.errors.classifier.is_context_overflow", lambda e: True)
    monkeypatch.setattr("myrm_agent_harness.toolkits.llms.errors.classifier.parse_available_output_tokens_from_error", lambda e: 400)

    async def mock_acreate(*args, **kwargs):
        raise error

    chat_model.client.acreate = mock_acreate

    with pytest.raises(Exception, match="context overflow"):
        await chat_model._agenerate(messages)

async def test_async_ephemeral_output_cap_retry(chat_model, messages, monkeypatch):
    error = Exception("context overflow")
    monkeypatch.setattr("myrm_agent_harness.toolkits.llms.errors.classifier.is_context_overflow", lambda e: True)
    monkeypatch.setattr("myrm_agent_harness.toolkits.llms.errors.classifier.parse_available_output_tokens_from_error", lambda e: 600)

    mock_response = {
        "choices": [{"message": {"role": "assistant", "content": "success"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }

    call_count = 0
    async def mock_acreate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise error
        return mock_response

    chat_model.client.acreate = mock_acreate

    result = await chat_model._agenerate(messages)

    assert call_count == 2
    assert result.generations[0].message.content == "success"

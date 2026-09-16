"""Unit tests for non-standard OpenAI gateway reasoning extraction and 400 parameter downgrade.

Tests:
1. Multi-candidate reasoning extraction (reasoning_content, reasoning, thinking, thoughts, reasoning_text)
2. Array-of-blocks thinking format (Anthropic / custom gateways)
3. Object attribute-based reasoning extraction
4. 400 Bad Request parameter downgrade detection & stripping (stream_options, parallel_tool_calls, reasoning_effort)
5. Sync & Async mixin integration with custom gateways
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.adapters.gateway_normalizer import (
    is_gateway_param_rejection,
    is_transport_stripped,
    remember_stripped_transport,
    sanitize_gateway_params_on_400,
)
from myrm_agent_harness.toolkits.llms.adapters.streaming import (
    extract_reasoning_payload,
)


class TestExtractReasoningPayload:
    """Test extract_reasoning_payload with various non-standard gateway response shapes."""

    def test_none_returns_empty_string(self) -> None:
        assert extract_reasoning_payload(None) == ""

    def test_standard_reasoning_content_dict(self) -> None:
        delta = {"content": "hello", "reasoning_content": "let me think step by step"}
        assert extract_reasoning_payload(delta) == "let me think step by step"

    def test_ollama_thinking_field(self) -> None:
        delta = {"content": "world", "thinking": "analyzing user intent..."}
        assert extract_reasoning_payload(delta) == "analyzing user intent..."

    def test_oneapi_reasoning_field(self) -> None:
        delta = {"content": "", "reasoning": "retrieving context..."}
        assert extract_reasoning_payload(delta) == "retrieving context..."

    def test_custom_thoughts_field(self) -> None:
        delta = {"content": "", "thoughts": "evaluating math formula"}
        assert extract_reasoning_payload(delta) == "evaluating math formula"

    def test_reasoning_text_field(self) -> None:
        delta = {"content": "", "reasoning_text": "calculating optimal route"}
        assert extract_reasoning_payload(delta) == "calculating optimal route"

    def test_thinking_block_array_of_dicts(self) -> None:
        delta = {
            "thinking": [
                {"type": "thinking", "thinking": "Step 1: plan"},
                {"type": "thinking", "text": " Step 2: execute"},
            ]
        }
        assert extract_reasoning_payload(delta) == "Step 1: plan Step 2: execute"

    def test_thinking_block_array_of_strings(self) -> None:
        delta = {"thinking": ["First, ", "Second, ", "Done."]}
        assert extract_reasoning_payload(delta) == "First, Second, Done."

    def test_nested_choices_structure_fallback(self) -> None:
        # Some gateways wrap the delta under choices[0].delta or choices[0].message
        chunk = {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "thinking": "analyzing request from nested choices",
                    },
                }
            ]
        }
        # Direct extraction on delta vs safe fallback
        assert extract_reasoning_payload(chunk["choices"][0]["delta"]) == "analyzing request from nested choices"

    def test_object_attribute_access(self) -> None:
        class FakeDelta:
            thinking = "object thinking attribute"

        assert extract_reasoning_payload(FakeDelta()) == "object thinking attribute"

    def test_priority_order_candidates(self) -> None:
        # reasoning_content comes before thinking
        delta = {"reasoning_content": "primary", "thinking": "secondary"}
        assert extract_reasoning_payload(delta) == "primary"


class TestGateway400Downgrade:
    """Test 400 Bad Request error detection and parameter sanitization."""

    def test_detect_stream_options_rejection(self) -> None:
        exc = Exception("BadRequestError: 400 Extra inputs are not permitted: stream_options")
        assert is_gateway_param_rejection(exc) is True

    def test_detect_parallel_tool_calls_rejection(self) -> None:
        exc = Exception("BadRequestError: 400 Unsupported parameter: parallel_tool_calls")
        assert is_gateway_param_rejection(exc) is True

    def test_detect_reasoning_effort_rejection(self) -> None:
        exc = Exception("BadRequestError: 400 Unknown field: reasoning_effort")
        assert is_gateway_param_rejection(exc) is True

    def test_ignore_unrelated_errors(self) -> None:
        exc = Exception("AuthenticationError: 401 Invalid API key")
        assert is_gateway_param_rejection(exc) is False

    def test_sanitize_params_strips_stream_options(self) -> None:
        params = {
            "model": "openai/gpt-4o",
            "stream": True,
            "stream_options": {"include_usage": True},
            "allowed_openai_params": ["model", "stream", "stream_options"],
        }
        exc = Exception("400 Bad Request: unsupported stream_options")
        stripped = sanitize_gateway_params_on_400(params, exc)

        assert stripped == ["stream_options"]
        assert "stream_options" not in params
        assert params["allowed_openai_params"] == ["model", "stream"]

    def test_sanitize_params_strips_parallel_tool_calls(self) -> None:
        params = {
            "model": "custom-model",
            "parallel_tool_calls": False,
            "allowed_openai_params": ["model", "parallel_tool_calls"],
        }
        exc = Exception("400 unknown field parallel_tool_calls")
        stripped = sanitize_gateway_params_on_400(params, exc)

        assert stripped == ["parallel_tool_calls"]
        assert "parallel_tool_calls" not in params
        assert params["allowed_openai_params"] == ["model"]

    def test_detect_max_completion_tokens_rejection(self) -> None:
        exc = Exception("BadRequestError: 400 Unknown field: max_completion_tokens")
        assert is_gateway_param_rejection(exc) is True

    def test_detect_temperature_rejection(self) -> None:
        exc = Exception("BadRequestError: 400 Unsupported value: 'temperature' is not supported for this model")
        assert is_gateway_param_rejection(exc) is True

    def test_detect_response_format_rejection(self) -> None:
        exc = Exception("BadRequestError: 400 Unsupported parameter: response_format")
        assert is_gateway_param_rejection(exc) is True

    def test_sanitize_params_maps_max_completion_tokens_to_max_tokens(self) -> None:
        params = {
            "model": "deepseek-r1",
            "max_completion_tokens": 4096,
            "allowed_openai_params": ["model", "max_completion_tokens"],
        }
        exc = Exception("400 unknown field max_completion_tokens")
        stripped = sanitize_gateway_params_on_400(params, exc)

        assert stripped == ["max_completion_tokens"]
        assert "max_completion_tokens" not in params
        assert params["max_tokens"] == 4096
        assert "max_tokens" in params["allowed_openai_params"]
        assert "max_completion_tokens" not in params["allowed_openai_params"]

    def test_sanitize_params_strips_temperature_on_unsupported(self) -> None:
        params = {
            "model": "o1-preview",
            "temperature": 0.7,
            "allowed_openai_params": ["model", "temperature"],
        }
        exc = Exception("400 'temperature' does not support 0.7 for this model")
        stripped = sanitize_gateway_params_on_400(params, exc)

        assert stripped == ["temperature"]
        assert "temperature" not in params
        assert params["allowed_openai_params"] == ["model"]

    def test_sanitize_params_strips_response_format(self) -> None:
        params = {
            "model": "local-model",
            "response_format": {"type": "json_object"},
            "allowed_openai_params": ["model", "response_format"],
        }
        exc = Exception("400 unsupported parameter response_format")
        stripped = sanitize_gateway_params_on_400(params, exc)

        assert stripped == ["response_format"]
        assert "response_format" not in params
        assert params["allowed_openai_params"] == ["model"]

    def test_detect_top_p_conflict_rejection(self) -> None:
        exc = Exception("BadRequestError: 400 temperature and top_p are mutually exclusive for this model")
        assert is_gateway_param_rejection(exc) is True

    def test_sanitize_params_strips_top_p_on_conflict(self) -> None:
        params = {
            "model": "moonshot-v1-8k",
            "temperature": 0.7,
            "top_p": 0.95,
            "allowed_openai_params": ["model", "temperature", "top_p"],
        }
        exc = Exception("BadRequestError: 400 temperature and top_p cannot both be set")
        stripped = sanitize_gateway_params_on_400(params, exc)

        assert stripped == ["top_p"]
        assert "top_p" not in params
        assert "temperature" in params
        assert params["allowed_openai_params"] == ["model", "temperature"]


def _internal_transport_response_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "tool_calls_transport",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"tool_calls": {"type": "array"}},
                "required": ["tool_calls"],
            },
        },
    }


class TestStructuredOutputSchemaDowngrade:
    """Schema-shape 400s strip only the internally injected tool-call transport."""

    def test_detect_object_without_properties_rejection(self) -> None:
        exc = Exception(
            "BadRequestError: OpenAIException - [400]: Error from provider: "
            "Upstream request failed: [invalid_request_error] "
            "An object with no properties is not allowed."
        )
        assert is_gateway_param_rejection(exc) is True

    def test_detect_grammar_backend_rejection(self) -> None:
        exc = Exception("Error code: 400 - {'error': {'message': 'guided_grammar xgrammar failed'}}")
        assert is_gateway_param_rejection(exc) is True

    def test_sanitize_strips_internal_transport_only(self) -> None:
        params = {
            "model": "openai/qwen2.5-7b",
            "response_format": _internal_transport_response_format(),
            "allowed_openai_params": ["model", "response_format"],
        }
        exc = Exception("[invalid_request_error] An object with no properties is not allowed.")
        stripped = sanitize_gateway_params_on_400(
            params, exc, model="openai/qwen2.5-7b", base_url="http://127.0.0.1:11434/v1"
        )

        assert stripped == ["response_format"]
        assert "response_format" not in params
        assert params["allowed_openai_params"] == ["model"]
        assert is_transport_stripped(model="openai/qwen2.5-7b", base_url="http://127.0.0.1:11434/v1") is True

    def test_sanitize_preserves_user_response_format(self) -> None:
        params = {
            "model": "openai/gpt-4o",
            "response_format": {"type": "json_object"},
            "allowed_openai_params": ["model", "response_format"],
        }
        exc = Exception("[invalid_request_error] An object with no properties is not allowed.")
        stripped = sanitize_gateway_params_on_400(params, exc)

        assert stripped == []
        assert params["response_format"] == {"type": "json_object"}

    def test_sanitize_strips_transport_from_extra_body(self) -> None:
        params = {
            "model": "openai/qwen2.5-7b",
            "extra_body": {"response_format": _internal_transport_response_format()},
        }
        exc = Exception("compile_grammar_error: backend missing")
        stripped = sanitize_gateway_params_on_400(params, exc)

        assert stripped == ["response_format"]
        assert "response_format" not in params["extra_body"]

    def test_transport_memo_roundtrip(self) -> None:
        assert is_transport_stripped(model="m/unique-model-xyz", base_url="http://127.0.0.1:9/v1") is False
        remember_stripped_transport(model="m/unique-model-xyz", base_url="http://127.0.0.1:9/v1")
        assert is_transport_stripped(model="m/unique-model-xyz", base_url="http://127.0.0.1:9/v1") is True
        assert is_transport_stripped(model="m/other-model", base_url="http://127.0.0.1:9/v1") is False

    def test_transport_memo_evicts_oldest_at_cap(self) -> None:
        from myrm_agent_harness.toolkits.llms.adapters import gateway_normalizer as gn

        saved = dict(gn._TRANSPORT_STRIP_MEMO)
        gn._TRANSPORT_STRIP_MEMO.clear()
        try:
            for i in range(gn._TRANSPORT_STRIP_MEMO_CAP):
                remember_stripped_transport(model=f"m/cap-evict-{i}", base_url="http://127.0.0.1:9/v1")
            assert len(gn._TRANSPORT_STRIP_MEMO) == gn._TRANSPORT_STRIP_MEMO_CAP
            assert is_transport_stripped(model="m/cap-evict-0", base_url="http://127.0.0.1:9/v1") is True
            remember_stripped_transport(model="m/cap-evict-new", base_url="http://127.0.0.1:9/v1")
            assert len(gn._TRANSPORT_STRIP_MEMO) == gn._TRANSPORT_STRIP_MEMO_CAP
            assert is_transport_stripped(model="m/cap-evict-0", base_url="http://127.0.0.1:9/v1") is False
            assert is_transport_stripped(model="m/cap-evict-new", base_url="http://127.0.0.1:9/v1") is True
        finally:
            gn._TRANSPORT_STRIP_MEMO.clear()
            gn._TRANSPORT_STRIP_MEMO.update(saved)


def _agenerate_success_payload(content: str = "ok") -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class TestAsyncAgenerateSchemaDowngrade:
    """Async non-streaming path strips the internal transport on schema-shape 400s."""

    @pytest.mark.asyncio
    async def test_async_agenerate_retries_without_internal_transport(self, monkeypatch: pytest.MonkeyPatch) -> None:
        model = ChatLiteLLM(model="openai/test-schema-downgrade-async")
        model.client = MagicMock()
        params = {
            "model": "openai/test-schema-downgrade-async",
            "response_format": _internal_transport_response_format(),
            "allowed_openai_params": ["model", "response_format"],
        }
        monkeypatch.setattr(
            model, "_create_message_dicts", lambda *args, **kwargs: ([{"role": "user", "content": "hi"}], params)
        )
        schema_error = Exception("[invalid_request_error] An object with no properties is not allowed.")
        mock_acreate = AsyncMock(side_effect=[schema_error, _agenerate_success_payload()])
        model.client.acreate = mock_acreate

        result = await model._agenerate([HumanMessage(content="hi")])

        assert result.generations[0].message.content == "ok"
        assert mock_acreate.call_count == 2
        _, retry_kwargs = mock_acreate.call_args_list[1]
        assert "response_format" not in retry_kwargs
        assert is_transport_stripped(model="openai/test-schema-downgrade-async", base_url="") is True

    @pytest.mark.asyncio
    async def test_async_agenerate_preserves_user_response_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        model = ChatLiteLLM(model="openai/test-schema-downgrade-user")
        model.client = MagicMock()
        params = {
            "model": "openai/test-schema-downgrade-user",
            "response_format": {"type": "json_object"},
            "allowed_openai_params": ["model", "response_format"],
        }
        monkeypatch.setattr(
            model, "_create_message_dicts", lambda *args, **kwargs: ([{"role": "user", "content": "hi"}], params)
        )
        schema_error = Exception("[invalid_request_error] An object with no properties is not allowed.")
        mock_acreate = AsyncMock(side_effect=schema_error)
        model.client.acreate = mock_acreate

        with pytest.raises(Exception, match="no properties"):
            await model._agenerate([HumanMessage(content="hi")])

        assert mock_acreate.call_count == 1
        assert params["response_format"] == {"type": "json_object"}


class TestSyncGenerateSchemaDowngrade:
    """Sync generate path strips the internal transport on schema-shape 400s."""

    def test_sync_generate_retries_without_internal_transport(self, monkeypatch: pytest.MonkeyPatch) -> None:
        model = ChatLiteLLM(model="openai/test-schema-downgrade-sync")
        model.client = MagicMock()
        params = {
            "model": "openai/test-schema-downgrade-sync",
            "response_format": _internal_transport_response_format(),
            "allowed_openai_params": ["model", "response_format"],
        }
        monkeypatch.setattr(
            model, "_create_message_dicts", lambda *args, **kwargs: ([{"role": "user", "content": "hi"}], params)
        )
        schema_error = Exception("[invalid_request_error] An object with no properties is not allowed.")
        mock_completion = MagicMock(side_effect=[schema_error, _agenerate_success_payload()])
        model.client.completion = mock_completion

        result = model._generate([HumanMessage(content="hi")])

        assert result.generations[0].message.content == "ok"
        assert mock_completion.call_count == 2
        _, retry_kwargs = mock_completion.call_args_list[1]
        assert "response_format" not in retry_kwargs

    def test_sync_generate_preserves_user_response_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        model = ChatLiteLLM(model="openai/test-schema-downgrade-sync-user")
        model.client = MagicMock()
        params = {
            "model": "openai/test-schema-downgrade-sync-user",
            "response_format": {"type": "json_object"},
            "allowed_openai_params": ["model", "response_format"],
        }
        monkeypatch.setattr(
            model, "_create_message_dicts", lambda *args, **kwargs: ([{"role": "user", "content": "hi"}], params)
        )
        schema_error = Exception("[invalid_request_error] An object with no properties is not allowed.")
        mock_completion = MagicMock(side_effect=schema_error)
        model.client.completion = mock_completion

        with pytest.raises(Exception, match="no properties"):
            model._generate([HumanMessage(content="hi")])

        assert mock_completion.call_count == 1
        assert params["response_format"] == {"type": "json_object"}


class TestSyncStreamSchemaDowngrade:
    """Sync streaming path strips the internal transport on schema-shape 400s."""

    def test_sync_stream_retries_without_internal_transport(self, monkeypatch: pytest.MonkeyPatch) -> None:
        model = ChatLiteLLM(model="openai/test-schema-downgrade-stream")
        model.client = MagicMock()
        params = {
            "model": "openai/test-schema-downgrade-stream",
            "response_format": _internal_transport_response_format(),
            "allowed_openai_params": ["model", "response_format"],
        }
        monkeypatch.setattr(
            model, "_create_message_dicts", lambda *args, **kwargs: ([{"role": "user", "content": "hi"}], params)
        )
        chunks = [
            {"choices": [{"delta": {"role": "assistant", "content": "ok"}, "finish_reason": None, "index": 0}]},
            {"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}], "usage": {"total_tokens": 30}},
        ]
        schema_error = Exception("[invalid_request_error] An object with no properties is not allowed.")
        mock_completion = MagicMock(side_effect=[schema_error, iter(chunks)])
        model.client.completion = mock_completion

        out = list(model._stream([HumanMessage(content="hi")]))

        assert len(out) > 0
        assert mock_completion.call_count == 2
        _, retry_kwargs = mock_completion.call_args_list[1]
        assert "response_format" not in retry_kwargs

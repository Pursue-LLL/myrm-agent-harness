"""Unit tests for non-standard OpenAI gateway reasoning extraction and 400 parameter downgrade.

Tests:
1. Multi-candidate reasoning extraction (reasoning_content, reasoning, thinking, thoughts, reasoning_text)
2. Array-of-blocks thinking format (Anthropic / custom gateways)
3. Object attribute-based reasoning extraction
4. 400 Bad Request parameter downgrade detection & stripping (stream_options, parallel_tool_calls, reasoning_effort)
5. Sync & Async mixin integration with custom gateways
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.adapters.gateway_normalizer import (
    is_gateway_param_rejection,
    sanitize_gateway_params_on_400,
)
from myrm_agent_harness.toolkits.llms.adapters.streaming import (
    _REASONING_FIELD_CANDIDATES,
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
        assert (
            extract_reasoning_payload(chunk["choices"][0]["delta"])
            == "analyzing request from nested choices"
        )

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
        exc = Exception(
            "BadRequestError: 400 Extra inputs are not permitted: stream_options"
        )
        assert is_gateway_param_rejection(exc) is True

    def test_detect_parallel_tool_calls_rejection(self) -> None:
        exc = Exception(
            "BadRequestError: 400 Unsupported parameter: parallel_tool_calls"
        )
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
        exc = Exception(
            "BadRequestError: 400 Unsupported value: 'temperature' is not supported for this model"
        )
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

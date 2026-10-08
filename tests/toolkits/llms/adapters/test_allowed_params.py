"""Tests for per-call ``allowed_openai_params`` injection."""

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.adapters.chat_model.allowed_params import inject_allowed_params
from myrm_agent_harness.toolkits.llms.adapters.chat_model.exceptions import _FRAMEWORK_REQUIRED_OPENAI_PARAMS


def test_adapter_uses_this_injector() -> None:
    assert ChatLiteLLM._inject_allowed_params is inject_allowed_params


def test_whitelists_supplied_keys_and_framework_params() -> None:
    params: dict[str, object] = {"model": "openai/gpt-4o", "top_k": 5}

    inject_allowed_params(params)

    allowed = params["allowed_openai_params"]
    assert allowed == sorted({"model", "top_k", *_FRAMEWORK_REQUIRED_OPENAI_PARAMS})


def test_allowed_tools_tool_choice_is_left_to_the_gateway() -> None:
    params: dict[str, object] = {"model": "openai/gpt-4o", "tool_choice": {"type": "allowed_tools"}}

    inject_allowed_params(params)

    assert "tool_choice" not in params["allowed_openai_params"]  # type: ignore[operator]


def test_native_anthropic_call_gets_no_whitelist() -> None:
    params: dict[str, object] = {
        "model": "anthropic/claude-sonnet-4-20250514",
        "stream_options": {"include_usage": True},
        "reasoning_effort": "low",
    }

    inject_allowed_params(params)

    assert "allowed_openai_params" not in params
    assert params["stream_options"] == {"include_usage": True}


def test_claude_behind_a_gateway_keeps_the_whitelist() -> None:
    params: dict[str, object] = {"model": "openai/claude-sonnet-4", "api_base": "https://gateway.example.com/v1"}

    inject_allowed_params(params)

    assert "allowed_openai_params" in params


def test_explicit_custom_provider_decides() -> None:
    native: dict[str, object] = {"model": "claude-sonnet-4-20250514", "custom_llm_provider": "anthropic"}
    other: dict[str, object] = {"model": "claude-sonnet-4-20250514", "custom_llm_provider": "openai"}

    inject_allowed_params(native)
    inject_allowed_params(other)

    assert "allowed_openai_params" not in native
    assert "allowed_openai_params" in other

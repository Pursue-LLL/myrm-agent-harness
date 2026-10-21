"""Tests for ChatLiteLLM.bind_tools tool_choice passthrough."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM


def test_bind_tools_passes_allowed_tools_dict_tool_choice() -> None:
    llm = ChatLiteLLM(model="gpt-4o")
    allowed_choice = {
        "type": "allowed_tools",
        "mode": "auto",
        "tools": [{"type": "function", "name": "file_write_tool"}],
    }

    with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind:
        llm.bind_tools([], tool_choice=allowed_choice)

    bind_kwargs = mock_bind.call_args.kwargs
    assert bind_kwargs["tool_choice"] == allowed_choice


def test_bind_tools_passes_string_tool_choice_auto() -> None:
    llm = ChatLiteLLM(model="gpt-4o")

    with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind:
        llm.bind_tools([], tool_choice="auto")

    assert mock_bind.call_args.kwargs["tool_choice"] == "auto"


def test_bind_tools_passes_named_function_tool_choice() -> None:
    llm = ChatLiteLLM(model="gpt-4o")

    with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind:
        llm.bind_tools([], tool_choice="echo_tool")

    assert mock_bind.call_args.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "echo_tool"},
    }


def test_inject_allowed_params_excludes_allowed_tools_from_force_whitelist() -> None:
    params: dict[str, object] = {
        "tool_choice": {
            "type": "allowed_tools",
            "mode": "auto",
            "tools": [{"type": "function", "name": "file_write_tool"}],
        },
        "tools": [],
    }
    ChatLiteLLM._inject_allowed_params(params)
    assert "tool_choice" not in params["allowed_openai_params"]


def test_bind_tools_injects_grammar_json_schema_for_local_endpoints() -> None:
    """Local weak model endpoints (e.g. llama-server on localhost) get structured tool call schema."""
    llm = ChatLiteLLM(model="openai/qwen2.5-coder:7b", api_base="http://127.0.0.1:11434/v1")
    sample_tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]

    with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind:
        llm.bind_tools(sample_tools)

    bind_kwargs = mock_bind.call_args.kwargs
    assert "response_format" in bind_kwargs
    rf = bind_kwargs["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "tool_calls_transport"


def test_bind_tools_skips_grammar_json_schema_for_gateway_on_gateway_port() -> None:
    """An OpenAI-compatible gateway on a gateway port keeps native tool calling.

    Regression (browser takeover gate never fired): ports 8000/8080 are served by
    LiteLLM proxy / one-api / vLLM alike, so they are not engine evidence. Injecting the
    constrained transport there strips native tool calls and strict gateways 400 with
    "An object with no properties is not allowed".
    """
    sample_tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]

    for gateway_url in ("http://127.0.0.1:8000/v1", "http://127.0.0.1:8080/v1"):
        llm = ChatLiteLLM(
            model="gemini-3-pro",
            api_base=gateway_url,
            custom_llm_provider="openai-like",
        )
        with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind:
            llm.bind_tools(sample_tools)
        assert "response_format" not in mock_bind.call_args.kwargs, (
            f"gateway on {gateway_url} must keep native tool calling"
        )


def test_bind_tools_skips_grammar_json_schema_for_cloud_endpoints() -> None:
    """Cloud endpoints (e.g. OpenAI/Anthropic) use native tool calling without forcing response_format."""
    llm = ChatLiteLLM(model="gpt-4o", api_base="https://api.openai.com/v1")
    sample_tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]

    with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind:
        llm.bind_tools(sample_tools)

    bind_kwargs = mock_bind.call_args.kwargs
    assert "response_format" not in bind_kwargs


def test_bind_tools_skips_transport_for_memoized_endpoint() -> None:
    """Endpoints that already rejected the transport skip injection (endpoint memory)."""
    from myrm_agent_harness.toolkits.llms.adapters.gateway_normalizer import (
        _TRANSPORT_STRIP_MEMO,
        is_transport_stripped,
        remember_stripped_transport,
    )

    model_id = "openai/memo-probe-xyz"
    base_url = "http://127.0.0.1:11434/v1"
    saved = dict(_TRANSPORT_STRIP_MEMO)
    try:
        assert is_transport_stripped(model=model_id, base_url=base_url) is False
        llm = ChatLiteLLM(model=model_id, api_base=base_url)
        sample_tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]

        remember_stripped_transport(model=model_id, base_url=base_url)
        with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind:
            llm.bind_tools(sample_tools)

        assert "response_format" not in mock_bind.call_args.kwargs
    finally:
        _TRANSPORT_STRIP_MEMO.clear()
        _TRANSPORT_STRIP_MEMO.update(saved)

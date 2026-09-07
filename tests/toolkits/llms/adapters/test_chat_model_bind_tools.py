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
    llm = ChatLiteLLM(model="openai/qwen2.5-coder:7b", api_base="http://127.0.0.1:8080/v1")
    sample_tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]

    with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind:
        llm.bind_tools(sample_tools)

    bind_kwargs = mock_bind.call_args.kwargs
    assert "response_format" in bind_kwargs
    rf = bind_kwargs["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "tool_calls_transport"


def test_bind_tools_skips_grammar_json_schema_for_cloud_endpoints() -> None:
    """Cloud endpoints (e.g. OpenAI/Anthropic) use native tool calling without forcing response_format."""
    llm = ChatLiteLLM(model="gpt-4o", api_base="https://api.openai.com/v1")
    sample_tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]

    with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind:
        llm.bind_tools(sample_tools)

    bind_kwargs = mock_bind.call_args.kwargs
    assert "response_format" not in bind_kwargs


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

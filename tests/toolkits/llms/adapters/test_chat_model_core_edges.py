"""Edge-path coverage for ChatLiteLLM core generation surface.

Complements the chat_model unit suites by exercising the fallback branches,
structured-output variants, tool_choice mapping, message-mixin normalization
edges, and converter utilities that the happy-path tests skip.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM, clean_model_kwargs
from myrm_agent_harness.toolkits.llms.adapters.chat_model.exceptions import EmptyChoicesError
from myrm_agent_harness.toolkits.llms.adapters.converters import (
    _convert_raw_tool_call_to_langchain,
    _resolve_tool_schema,
)
from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import ToolCallDict


def _make_model(model: str = "gpt-5-chat", **kwargs) -> ChatLiteLLM:
    return ChatLiteLLM.model_construct(client=MagicMock(), model=model, **kwargs)


class _PydanticSchema(BaseModel):
    x: int


# ---------------------------------------------------------------------------
# _client_params / _convert_response_to_dict
# ---------------------------------------------------------------------------


class TestClientParams:
    def test_client_params_requires_initialized_client(self) -> None:
        llm = ChatLiteLLM.model_construct(model="gpt-5-chat", client=None)
        with pytest.raises(RuntimeError, match="client not initialized"):
            _ = llm._client_params


class TestConvertResponseToDict:
    def test_accepts_dict(self) -> None:
        assert _make_model()._convert_response_to_dict({"a": 1}) == {"a": 1}

    def test_uses_model_dump(self) -> None:
        class _WithDump:
            def model_dump(self) -> dict[str, object]:
                return {"x": 1}

        assert _make_model()._convert_response_to_dict(_WithDump()) == {"x": 1}

    def test_uses_dict_method(self) -> None:
        class _WithDict:
            def dict(self) -> dict[str, object]:
                return {"y": 2}

        assert _make_model()._convert_response_to_dict(_WithDict()) == {"y": 2}

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unable to convert"):
            _make_model()._convert_response_to_dict(object())


# ---------------------------------------------------------------------------
# ainvoke fallback branches
# ---------------------------------------------------------------------------


class TestAinvokeFallbacks:
    async def test_in_fallback_cleans_kwargs(self) -> None:
        with patch.object(BaseChatModel, "ainvoke", new_callable=AsyncMock) as mock_ainvoke:
            mock_ainvoke.return_value = AIMessage(content="ok")
            result = await _make_model().ainvoke(
                "hi", config=None, _in_fallback=True, temperature=0.5
            )
        assert result.content == "ok"
        mock_ainvoke.assert_awaited_once()
        fallback_kwargs = mock_ainvoke.await_args.kwargs
        assert "temperature" in fallback_kwargs

    async def test_json_mode_fallback_returns_reasoning_content(self) -> None:
        reasoning = '{"answer": 42}'
        with patch.object(BaseChatModel, "ainvoke", new_callable=AsyncMock) as mock_ainvoke:
            mock_ainvoke.return_value = AIMessage(
                content="",
                additional_kwargs={"reasoning_content": reasoning},
            )
            result = await _make_model().ainvoke("hi", config=None, _json_mode_fallback=True)
        assert result.content == reasoning

    async def test_json_mode_fallback_retries_with_clean_kwargs(self) -> None:
        with patch.object(BaseChatModel, "ainvoke", new_callable=AsyncMock) as mock_ainvoke:
            mock_ainvoke.side_effect = [AIMessage(content="   "), AIMessage(content="ok")]
            result = await _make_model().ainvoke("hi", config=None, _json_mode_fallback=True)
        assert result.content == "ok"
        assert mock_ainvoke.await_count == 2
        second_kwargs = mock_ainvoke.await_args.kwargs
        assert second_kwargs["_in_fallback"] is True


# ---------------------------------------------------------------------------
# with_structured_output variants
# ---------------------------------------------------------------------------


class TestWithStructuredOutput:
    def test_rejects_unsupported_kwargs(self) -> None:
        with pytest.raises(ValueError, match="unsupported arguments"):
            _make_model().with_structured_output({"type": "object"}, foo=1)

    def test_json_schema_injects_response_format(self) -> None:
        with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind:
            _make_model().with_structured_output({"type": "object"})
        assert mock_bind.call_args.kwargs["response_format"] == {"type": "json_object"}
        assert mock_bind.call_args.kwargs["stream"] is False

    def test_pydantic_schema_builds_output_parser(self) -> None:
        with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()):
            runnable = _make_model().with_structured_output(_PydanticSchema)
        assert runnable is not None

    def test_skips_response_format_for_denylisted_model(self) -> None:
        with (
            patch.object(ChatLiteLLM, "should_skip_response_format", return_value=True),
            patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind,
        ):
            _make_model().with_structured_output({"type": "object"})
        assert "response_format" not in mock_bind.call_args.kwargs

    def test_include_raw_uses_fallback_chain(self) -> None:
        with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()):
            runnable = _make_model().with_structured_output({"type": "object"}, include_raw=True)
        assert runnable is not None


# ---------------------------------------------------------------------------
# bind_tools mapping branches
# ---------------------------------------------------------------------------


class TestBindToolsEdges:
    def test_none_and_required_choice(self) -> None:
        llm = ChatLiteLLM(model="gpt-4o")
        for choice in ("none", "required"):
            with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind:
                llm.bind_tools([], tool_choice=choice)
            assert mock_bind.call_args.kwargs["tool_choice"] == choice

    def test_any_maps_to_auto(self) -> None:
        llm = ChatLiteLLM(model="gpt-4o")
        with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind:
            llm.bind_tools([], tool_choice="any")
        assert mock_bind.call_args.kwargs["tool_choice"] == "auto"

    def test_parallel_tool_calls_and_extra_kwargs(self) -> None:
        llm = ChatLiteLLM(model="gpt-4o")
        tools = [
            {
                "type": "function",
                "function": {"name": "f", "parameters": {"type": "object"}},
            }
        ]
        with patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind:
            llm.bind_tools(tools, tool_choice="required", parallel_tool_calls=True, temperature=0.1)
        kwargs = mock_bind.call_args.kwargs
        assert kwargs["parallel_tool_calls"] is True
        assert kwargs["temperature"] == 0.1
        assert kwargs["tools"]
        assert kwargs["tool_choice"] == "required"

    def test_conversion_error_skips_tool(self) -> None:
        llm = ChatLiteLLM(model="gpt-4o")
        with (
            patch.object(ChatLiteLLM, "bind", return_value=MagicMock()) as mock_bind,
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.chat_model.model.normalize_tool_schema",
                side_effect=ValueError("boom"),
            ),
        ):
            llm.bind_tools([object()])
        assert mock_bind.call_args.kwargs["tools"] == []


# ---------------------------------------------------------------------------
# message-mixin normalization edges
# ---------------------------------------------------------------------------


class TestStringifyMessageContent:
    def test_mixed_list_blocks(self) -> None:
        content = ["  hello  ", {"type": "text", "text": " world "}, 42]
        assert _make_model()._stringify_message_content(content) == "hello\nworld\n42"

    def test_non_string_scalar(self) -> None:
        assert _make_model()._stringify_message_content(123) == "123"


class TestIsSystemRoleMessage:
    def test_mapping_role(self) -> None:
        assert _make_model()._is_system_role_message({"role": "system"}) is True
        assert _make_model()._is_system_role_message({"role": "user"}) is False

    def test_plain_object(self) -> None:
        assert _make_model()._is_system_role_message(object()) is False


class TestCreateMessageDictsEdges:
    def test_stop_conflict_raises(self) -> None:
        llm = _make_model()
        with (
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.chat_model.model.ChatLiteLLM._client_params",
                new_callable=PropertyMock,
                return_value={"stop": ["x"]},
            ),
            pytest.raises(ValueError, match=r"stop.*both the input and default params"),
        ):
            llm._create_message_dicts([HumanMessage(content="hi")], stop=["STOP"])

    def test_ok_with_stop_only_in_input(self) -> None:
        llm = _make_model()
        message_dicts, params = llm._create_message_dicts(
            [HumanMessage(content="hi")], stop=["STOP"]
        )
        assert message_dicts[0]["role"] == "user"
        assert params["stop"] == ["STOP"]


class TestNormalizeMessagesForProvider:
    def _minimax(self, **kwargs) -> ChatLiteLLM:
        return _make_model(
            "MiniMax-M2.5",
            api_base="https://api.minimaxi.com/v1",
            custom_llm_provider="minimax",
            **kwargs,
        )

    def test_demotes_and_drops_empty_system(self) -> None:
        result = self._minimax()._normalize_messages_for_provider(
            [SystemMessage(content=""), HumanMessage(content="hi")]
        )
        assert result == [HumanMessage(content="hi")]

    def test_demotes_list_content(self) -> None:
        result = self._minimax()._normalize_messages_for_provider(
            [
                SystemMessage(content="sys"),
                HumanMessage(content=[{"type": "text", "text": "hi"}]),
            ]
        )
        assert result[0].content == [
            {"type": "text", "text": "sys"},
            {"type": "text", "text": "hi"},
        ]

    def test_demotes_scalar_content(self) -> None:
        result = self._minimax()._normalize_messages_for_provider(
            [SystemMessage(content="sys"), HumanMessage(content="hi")]
        )
        assert result[0].content == "sys\n\nhi"

    def test_demotes_without_human_turn(self) -> None:
        result = self._minimax()._normalize_messages_for_provider(
            [SystemMessage(content="sys"), AIMessage(content="a")]
        )
        assert result[0] == HumanMessage(content="sys")


class TestStampReasoningContent:
    def test_stamps_empty_reasoning_content(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.llms.adapters.chat_model.message_mixin._capability_detector"
        ) as mock_detector:
            mock_detector.needs_reasoning_content_echo.return_value = True
            message_dicts = [{"role": "assistant", "content": "hi"}]
            _make_model()._stamp_missing_reasoning_content(message_dicts)
        assert message_dicts[0]["reasoning_content"] == ""

    def test_skips_when_not_required(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.llms.adapters.chat_model.message_mixin._capability_detector"
        ) as mock_detector:
            mock_detector.needs_reasoning_content_echo.return_value = False
            message_dicts = [{"role": "assistant", "content": "hi"}]
            _make_model()._stamp_missing_reasoning_content(message_dicts)
        assert "reasoning_content" not in message_dicts[0]


class TestBuildEmptyChoicesError:
    def test_includes_all_error_fields(self) -> None:
        message = _make_model()._build_empty_choices_error(
            {
                "error": "boom",
                "code": "E1",
                "type": "server_error",
                "original_exception": "trace",
            }
        )
        assert "Error: boom" in message
        assert "E1" in message
        assert "server_error" in message
        assert "trace" in message


class TestCreateChatResultEdges:
    def test_empty_choices_raises(self) -> None:
        with pytest.raises(EmptyChoicesError):
            _make_model()._create_chat_result({"usage": {}, "choices": []})

    def test_safety_termination_suppresses_tool_calls(self) -> None:
        result = _make_model()._create_chat_result(
            {
                "usage": {},
                "choices": [
                    {
                        "finish_reason": "content_filter",
                        "message": {
                            "role": "assistant",
                            "content": "blocked",
                            "tool_calls": [
                                {
                                    "id": "1",
                                    "type": "function",
                                    "function": {"name": "f", "arguments": "{"},
                                }
                            ],
                        },
                    }
                ],
            }
        )
        content = result.generations[0].message.content
        assert isinstance(content, str)
        assert content.startswith("blocked")
        assert "[Safety]" in content

    def test_message_conversion_error_re_raises(self) -> None:
        with pytest.raises(KeyError):
            _make_model()._create_chat_result(
                {
                    "usage": {},
                    "choices": [{"finish_reason": None, "message": {"role": "system"}}],
                }
            )


# ---------------------------------------------------------------------------
# converter utilities
# ---------------------------------------------------------------------------


class TestConverterUtilities:
    def test_resolve_tool_schema_strips_namespace(self) -> None:
        schemas = {"echo": {"name": "echo"}}
        assert _resolve_tool_schema("ns:echo", schemas) == {"name": "echo"}
        assert _resolve_tool_schema("missing", schemas) is None

    def test_raw_tool_call_with_dict_args_and_generated_id(self) -> None:
        tc: ToolCallDict = {
            "id": "",
            "type": "function",
            "function": {
                "name": "ns:echo",
                "arguments": {"text": "hi"},
            },
        }
        tool_call, metadata = _convert_raw_tool_call_to_langchain(tc)
        assert tool_call is not None
        assert tool_call["name"] == "echo"
        assert tool_call["args"] == {"text": "hi"}
        assert metadata is not None


# ---------------------------------------------------------------------------
# module-level facade
# ---------------------------------------------------------------------------


class TestCleanModelKwargsFacade:
    def test_module_function_delegates(self) -> None:
        result = clean_model_kwargs({"temperature": 0.2, "model": "x"}, "gpt-4")
        assert isinstance(result, dict)

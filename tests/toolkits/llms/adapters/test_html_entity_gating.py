"""HTML-entity decoding of tool-call arguments is opt-in per model (xAI Grok), never global.

Grok HTML-escapes characters inside tool-call argument strings (``&&`` -> ``&amp;&amp;``). For every
other model the argument strings are byte-exact data, so decoding them would corrupt legitimate entity
text such as the HTML source a file tool is asked to write.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.messages.tool import ToolCall

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.adapters.converters import (
    _parse_tool_call_args_result,
    convert_dict_to_message,
)
from myrm_agent_harness.toolkits.llms.adapters.model_capability import ModelCapabilityDetector
from myrm_agent_harness.toolkits.llms.adapters.stream_aggregator import StreamAggregator, finalize_stream
from myrm_agent_harness.toolkits.llms.adapters.tool_recovery import (
    build_final_tool_call_chunk,
    recover_tool_call_payloads,
)

ESCAPED_COMMAND = "echo &quot;hi&quot; &amp;&amp; ls"
DECODED_COMMAND = 'echo "hi" && ls'
HTML_SOURCE = "<p>Tom &amp; Jerry &lt;3</p>"


def _tool_call(arguments: dict[str, Any], name: str = "bash_code_execute_tool") -> dict[str, Any]:
    return {"id": "call_1", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def _tool_calls(message: BaseMessage) -> list[ToolCall]:
    assert isinstance(message, AIMessage)
    return message.tool_calls


class TestIsXaiModel:
    @pytest.mark.parametrize(
        "model",
        [
            "xai/grok-4",
            "grok-4",
            "Grok-3-Mini",
            "x-ai/grok-4-fast",
            "openrouter/x-ai/grok-code-fast-1",
            "openai/grok-3-mini",
            "xai/a-future-model-name",
        ],
    )
    def test_grok_model_ids(self, model: str) -> None:
        assert ModelCapabilityDetector().is_xai_model(model)

    @pytest.mark.parametrize(
        "model",
        [
            "",
            "gpt-4o",
            "claude-3-7-sonnet",
            "groq/llama-3.3-70b",
            "deepseek/deepseek-v4-flash",
            "grokking-7b",
            "acme/xaiphone-1",
        ],
    )
    def test_other_model_ids(self, model: str) -> None:
        assert not ModelCapabilityDetector().is_xai_model(model)


class TestDecodingIsOptInThroughTheChain:
    def test_args_result_keeps_entities_by_default(self) -> None:
        parsed, _ = _parse_tool_call_args_result({"command": ESCAPED_COMMAND}, "bash_code_execute_tool")

        assert parsed == {"command": ESCAPED_COMMAND}

    def test_args_result_decodes_when_requested(self) -> None:
        parsed, _ = _parse_tool_call_args_result(
            {"command": ESCAPED_COMMAND}, "bash_code_execute_tool", decode_html_entities=True
        )

        assert parsed == {"command": DECODED_COMMAND}

    @pytest.mark.parametrize(("decode", "expected"), [(False, ESCAPED_COMMAND), (True, DECODED_COMMAND)])
    def test_convert_dict_to_message(self, decode: bool, expected: str) -> None:
        payload = {"role": "assistant", "content": "", "tool_calls": [_tool_call({"command": ESCAPED_COMMAND})]}

        message = convert_dict_to_message(payload, decode_html_entities=decode)

        assert _tool_calls(message)[0]["args"] == {"command": expected}

    @pytest.mark.parametrize(("decode", "expected"), [(False, ESCAPED_COMMAND), (True, DECODED_COMMAND)])
    def test_recover_tool_call_payloads(self, decode: bool, expected: str) -> None:
        payloads, _ = recover_tool_call_payloads(
            [_tool_call({"command": ESCAPED_COMMAND})], decode_html_entities=decode
        )

        assert json.loads(payloads[0]["function"]["arguments"]) == {"command": expected}

    @pytest.mark.parametrize(("decode", "expected"), [(False, ESCAPED_COMMAND), (True, DECODED_COMMAND)])
    def test_build_final_tool_call_chunk(self, decode: bool, expected: str) -> None:
        _, recovered, _ = build_final_tool_call_chunk(
            [_tool_call({"command": ESCAPED_COMMAND})], decode_html_entities=decode
        )

        assert json.loads(recovered[0]["function"]["arguments"]) == {"command": expected}


class TestModelIdDrivesDecoding:
    """The non-streaming seam derives the opt-in from the configured model id."""

    @staticmethod
    def _response(arguments: dict[str, Any], name: str) -> dict[str, Any]:
        message = {"role": "assistant", "content": "", "tool_calls": [_tool_call(arguments, name)]}
        return {"choices": [{"message": message, "finish_reason": "tool_calls"}], "usage": {}}

    @pytest.mark.parametrize(
        ("model", "expected"),
        [("xai/grok-4", DECODED_COMMAND), ("gpt-4o", ESCAPED_COMMAND), ("deepseek/deepseek-v4-flash", ESCAPED_COMMAND)],
    )
    def test_non_stream_response(self, model: str, expected: str) -> None:
        chat_model = ChatLiteLLM(model=model)

        result = chat_model._create_chat_result(self._response({"command": ESCAPED_COMMAND}, "bash_code_execute_tool"))

        assert _tool_calls(result.generations[0].message)[0]["args"] == {"command": expected}

    @pytest.mark.parametrize(
        ("model", "expected"),
        [("xai/grok-4", DECODED_COMMAND), ("gpt-4o", ESCAPED_COMMAND)],
    )
    def test_finalize_stream_shared_by_sync_and_async_paths(self, model: str, expected: str) -> None:
        agg = StreamAggregator(AIMessageChunk)
        agg.finish_reason = "tool_calls"
        agg.tool_calls = [_tool_call({"command": ESCAPED_COMMAND})]

        result = finalize_stream(agg, None, model, is_async=True, record_usage_fn=lambda *args, **kwargs: None)

        assert result.final_tool_chunk is not None
        final_message = result.final_tool_chunk.message
        assert isinstance(final_message, AIMessageChunk)
        assert json.loads(final_message.tool_call_chunks[0]["args"] or "") == {"command": expected}

    def test_html_source_is_written_verbatim_by_non_grok_models(self) -> None:
        chat_model = ChatLiteLLM(model="gpt-4o")
        arguments = {"path": "index.html", "content": HTML_SOURCE}

        result = chat_model._create_chat_result(self._response(arguments, "file_write_tool"))

        assert _tool_calls(result.generations[0].message)[0]["args"] == arguments

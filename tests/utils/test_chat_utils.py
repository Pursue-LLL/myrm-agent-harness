"""Tests for myrm_agent_harness.utils.chat_utils."""

import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from myrm_agent_harness.utils.chat_utils import _extract_text_content, convert_chat_history_simple


class TestConvertChatHistorySimple:
    def test_empty_history_returns_empty_list(self) -> None:
        assert convert_chat_history_simple([]) == []
        assert convert_chat_history_simple(None) == []  # type: ignore[arg-type]

    def test_base_message_list_returned_as_is(self) -> None:
        msgs: list[BaseMessage] = [HumanMessage(content="hi")]
        out = convert_chat_history_simple(msgs)
        assert out is msgs

    def test_raw_role_content_to_messages(self) -> None:
        history = [["human", "u"], ["assistant", "a"]]
        out = convert_chat_history_simple(history)
        assert len(out) == 2
        assert isinstance(out[0], HumanMessage)
        assert out[0].content == "u"
        assert isinstance(out[1], AIMessage)
        assert out[1].content == "a"

    def test_agent_history_json_extracts_content(self) -> None:
        payload = json.dumps({"__agent_history": True, "content": "from_json"})
        history = [["assistant", payload]]
        out = convert_chat_history_simple(history)
        assert isinstance(out[0], AIMessage)
        assert out[0].content == "from_json"

    def test_multimedia_list_extracts_text_items(self) -> None:
        history = [
            [
                "human",
                [
                    {"type": "text", "text": "hello"},
                    {"type": "image", "url": "x"},
                    {"type": "text", "text": "world"},
                ],
            ]
        ]
        out = convert_chat_history_simple(history)
        assert out[0].content == "hello world"


class TestExtractTextContent:
    def test_plain_string_unchanged(self) -> None:
        assert _extract_text_content("plain") == "plain"

    def test_agent_history_json_extracts_content(self) -> None:
        s = json.dumps({"__agent_history": True, "content": "inner"})
        assert _extract_text_content(s) == "inner"

    def test_json_parse_failure_falls_back_to_raw_string(self) -> None:
        raw = '{"__agent_history": not valid json'
        assert _extract_text_content(raw) == raw

    def test_multimedia_list_text_parts(self) -> None:
        items = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
        assert _extract_text_content(items) == "a b"

    def test_list_non_dict_items_as_str(self) -> None:
        assert _extract_text_content([42, "x"]) == "42 x"

    def test_non_string_non_list_coerced_to_str(self) -> None:
        assert _extract_text_content(99) == "99"  # type: ignore[arg-type]

    def test_empty_text_list_falls_back_to_str_of_list(self) -> None:
        only_image = [{"type": "image", "url": "u"}]
        assert _extract_text_content(only_image) == str(only_image)

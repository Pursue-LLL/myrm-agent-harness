"""Tests for myrm_agent_harness.utils.chat_utils."""

import json

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from myrm_agent_harness.utils.chat_utils import (
    convert_chat_history_simple,
    extract_answer_text,
    extract_litellm_answer_text,
    extract_text_content,
    parse_llm_json_list,
    parse_llm_json_object,
)


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
        assert extract_text_content("plain") == "plain"

    def test_agent_history_json_extracts_content(self) -> None:
        s = json.dumps({"__agent_history": True, "content": "inner"})
        assert extract_text_content(s) == "inner"

    def test_json_parse_failure_falls_back_to_raw_string(self) -> None:
        raw = '{"__agent_history": not valid json'
        assert extract_text_content(raw) == raw

    def test_multimedia_list_text_parts(self) -> None:
        items = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
        assert extract_text_content(items) == "a b"

    def test_list_non_dict_items_as_str(self) -> None:
        assert extract_text_content([42, "x"]) == "42 x"

    def test_non_string_non_list_coerced_to_str(self) -> None:
        assert extract_text_content(99) == "99"  # type: ignore[arg-type]

    def test_empty_text_list_falls_back_to_str_of_list(self) -> None:
        only_image = [{"type": "image", "url": "u"}]
        assert extract_text_content(only_image) == str(only_image)


class _FakeResponse:
    def __init__(self, content: object, additional_kwargs: dict | None = None) -> None:
        self.content = content
        if additional_kwargs is not None:
            self.additional_kwargs = additional_kwargs


class TestExtractAnswerText:
    def test_plain_string_returned_as_is(self) -> None:
        assert extract_answer_text(_FakeResponse("answer")) == "answer"

    def test_none_content_without_reasoning_returns_empty(self) -> None:
        assert extract_answer_text(_FakeResponse(None)) == ""

    def test_reasoning_model_falls_back_to_reasoning_content(self) -> None:
        response = _FakeResponse(None, {"reasoning_content": "reasoned answer"})
        assert extract_answer_text(response) == "reasoned answer"

    def test_empty_string_content_falls_back_to_reasoning(self) -> None:
        response = _FakeResponse("", {"reasoning_content": "reasoned answer"})
        assert extract_answer_text(response) == "reasoned answer"

    def test_anthropic_block_list_extracts_text(self) -> None:
        response = _FakeResponse(
            [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]
        )
        assert extract_answer_text(response) == "hello world"

    def test_anthropic_empty_text_blocks_fall_back_to_reasoning(self) -> None:
        """Empty/missing text blocks must not leak the list repr."""
        response = _FakeResponse(
            [{"type": "text", "text": ""}],
            {"reasoning_content": "reasoned answer"},
        )
        assert extract_answer_text(response) == "reasoned answer"

    def test_anthropic_none_text_block_does_not_leak_none(self) -> None:
        """A text block whose text value is None must not leak the literal "None"."""
        response = _FakeResponse(
            [{"type": "text", "text": None}],
            {"reasoning_content": "reasoned answer"},
        )
        assert extract_answer_text(response) == "reasoned answer"

    def test_reasoning_content_non_string_ignored(self) -> None:
        response = _FakeResponse(None, {"reasoning_content": 42})
        assert extract_answer_text(response) == ""

    def test_inline_think_block_stripped(self) -> None:
        """Qwen3-style inline <think> block must be removed from the answer."""
        response = _FakeResponse(
            "<think>Let me plan this step by step.</think>Here is the answer"
        )
        assert extract_answer_text(response) == "Here is the answer"

    def test_content_only_think_block_falls_back_to_reasoning(self) -> None:
        """Content that is entirely a think block must fall back to reasoning_content."""
        response = _FakeResponse(
            "<think>Only internal reasoning, no answer.</think>",
            {"reasoning_content": "reasoned answer"},
        )
        assert extract_answer_text(response) == "reasoned answer"

    def test_inline_reasoning_variant_tags_stripped(self) -> None:
        """Other reasoning tag variants (thinking/reasoning) must also be stripped."""
        response = _FakeResponse(
            "<thinking>step one</thinking><reasoning>step two</reasoning>answer"
        )
        assert extract_answer_text(response) == "answer"

    def test_plain_content_with_lt_char_unchanged(self) -> None:
        """A '<' in ordinary text (not a paired tag) must be preserved."""
        response = _FakeResponse("a < b and c > d")
        assert extract_answer_text(response) == "a < b and c > d"

    def test_anthropic_block_list_with_inline_think_stripped(self) -> None:
        """Think block inside an Anthropic text block must also be stripped."""
        response = _FakeResponse(
            [{"type": "text", "text": "<think>plan</think>block answer"}]
        )
        assert extract_answer_text(response) == "block answer"


class _FakeLitellmMessage:
    def __init__(self, content: object, reasoning_content: str | None = None) -> None:
        self.content = content
        self.reasoning_content = reasoning_content


class _FakeLitellmResponse:
    def __init__(self, message: object) -> None:
        self.choices = [type("Choice", (), {"message": message})()]


class TestExtractLitellmAnswerText:
    def test_none_response_returns_empty(self) -> None:
        assert extract_litellm_answer_text(None) == ""

    def test_missing_choices_returns_empty(self) -> None:
        response = type("Resp", (), {"choices": []})()
        assert extract_litellm_answer_text(response) == ""

    def test_plain_string_content(self) -> None:
        msg = _FakeLitellmMessage("answer")
        assert extract_litellm_answer_text(_FakeLitellmResponse(msg)) == "answer"

    def test_reasoning_model_falls_back_to_reasoning_content(self) -> None:
        msg = _FakeLitellmMessage(None, "reasoned answer")
        assert (
            extract_litellm_answer_text(_FakeLitellmResponse(msg)) == "reasoned answer"
        )

    def test_empty_string_content_falls_back_to_reasoning(self) -> None:
        msg = _FakeLitellmMessage("", "reasoned answer")
        assert (
            extract_litellm_answer_text(_FakeLitellmResponse(msg)) == "reasoned answer"
        )

    def test_anthropic_block_list_extracts_text(self) -> None:
        msg = _FakeLitellmMessage(
            [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]
        )
        assert extract_litellm_answer_text(_FakeLitellmResponse(msg)) == "hello world"

    def test_plain_content_with_inline_think_stripped(self) -> None:
        msg = _FakeLitellmMessage("<think>plan</think>answer")
        assert extract_litellm_answer_text(_FakeLitellmResponse(msg)) == "answer"

    def test_block_list_with_inline_think_stripped(self) -> None:
        msg = _FakeLitellmMessage(
            [{"type": "text", "text": "<think>plan</think>block answer"}]
        )
        assert extract_litellm_answer_text(_FakeLitellmResponse(msg)) == "block answer"

    def test_content_only_think_falls_back_to_reasoning(self) -> None:
        msg = _FakeLitellmMessage("<think>only plan</think>", "reasoned answer")
        assert (
            extract_litellm_answer_text(_FakeLitellmResponse(msg)) == "reasoned answer"
        )

    def test_none_text_block_does_not_leak_none(self) -> None:
        msg = _FakeLitellmMessage([{"type": "text", "text": None}], "reasoned answer")
        assert (
            extract_litellm_answer_text(_FakeLitellmResponse(msg)) == "reasoned answer"
        )

    def test_reasoning_content_non_string_ignored(self) -> None:
        msg = _FakeLitellmMessage(None, "  ")
        assert extract_litellm_answer_text(_FakeLitellmResponse(msg)) == ""


class TestParseLlmJsonObject:
    def test_plain_object(self) -> None:
        assert parse_llm_json_object('{"done": true}') == {"done": True}

    def test_fenced_object(self) -> None:
        raw = "```json\n{\"a\": 1}\n```"
        assert parse_llm_json_object(raw) == {"a": 1}

    def test_prose_framing(self) -> None:
        raw = 'Here is the verdict: {"done": false}. Hope that helps.'
        assert parse_llm_json_object(raw) == {"done": False}

    def test_unescaped_newline_and_tab_in_string(self) -> None:
        raw = '{"main_topic": "line one\nline two", "structure": "a\tb"}'
        assert parse_llm_json_object(raw) == {
            "main_topic": "line one\nline two",
            "structure": "a\tb",
        }

    def test_last_object_wins(self) -> None:
        raw = '{"done": false} Example: {"done": true}'
        assert parse_llm_json_object(raw) == {"done": True}

    def test_brackets_inside_strings_ignored(self) -> None:
        raw = '{"s": "a } b", "t": "c { d"}'
        assert parse_llm_json_object(raw) == {"s": "a } b", "t": "c { d"}

    def test_no_object_returns_none(self) -> None:
        assert parse_llm_json_object("no json here") is None
        assert parse_llm_json_object("") is None

    def test_bare_control_char_escaped(self) -> None:
        raw = '{"a": "bell\u0007char"}'
        assert parse_llm_json_object(raw) == {"a": "bell\x07char"}

    def test_object_preceded_by_array_ignored(self) -> None:
        raw = '[1, 2] then {"done": true}'
        assert parse_llm_json_object(raw) == {"done": True}

    def test_require_key_filters_objects(self) -> None:
        raw = '{"a": 1} {"done": false} {"done": true}'
        assert parse_llm_json_object(raw, require_key="done") == {"done": True}

    def test_require_key_last_matching_wins(self) -> None:
        raw = '{"done": false} Example: {"done": true, "extra": 1}'
        assert parse_llm_json_object(raw, require_key="done") == {"done": True, "extra": 1}

    def test_require_key_no_match_returns_none(self) -> None:
        assert parse_llm_json_object('{"a": 1}', require_key="done") is None

    def test_require_key_none_matches_every_object(self) -> None:
        raw = '{"done": false} {"a": 1}'
        assert parse_llm_json_object(raw, require_key=None) == {"a": 1}

    def test_trailing_comma_in_object(self) -> None:
        raw = '{"done": true, "reason": "ok",}'
        assert parse_llm_json_object(raw) == {"done": True, "reason": "ok"}

    def test_trailing_comma_in_nested_values(self) -> None:
        raw = '{"a": [1, 2,], "b": "x",}'
        assert parse_llm_json_object(raw) == {"a": [1, 2], "b": "x"}

    def test_trailing_comma_strings_unaffected(self) -> None:
        raw = '{"s": "literal ,} stays", "t": "a,]",}'
        assert parse_llm_json_object(raw) == {"s": "literal ,} stays", "t": "a,]"}


class TestParseLlmJsonList:
    def test_plain_array(self) -> None:
        assert parse_llm_json_list('[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]

    def test_fenced_array(self) -> None:
        raw = "```json\n[1, 2, 3]\n```"
        assert parse_llm_json_list(raw) == [1, 2, 3]

    def test_prose_framing(self) -> None:
        raw = 'Suggestions: ["a", "b"] Enjoy!'
        assert parse_llm_json_list(raw) == ["a", "b"]

    def test_unescaped_newlines(self) -> None:
        raw = '["line one\nline two", "ok"]'
        assert parse_llm_json_list(raw) == ["line one\nline two", "ok"]

    def test_last_array_wins(self) -> None:
        raw = '["example"] Real: ["real"]'
        assert parse_llm_json_list(raw) == ["real"]

    def test_array_wrapped_in_object_returns_object_last(self) -> None:
        raw = '{"result": ["a"]}'
        assert parse_llm_json_list(raw) == ["a"]

    def test_no_array_returns_none(self) -> None:
        assert parse_llm_json_list("no array here") is None

    def test_trailing_comma_in_array(self) -> None:
        raw = '["a", "b",]'
        assert parse_llm_json_list(raw) == ["a", "b"]

    def test_trailing_comma_nested_and_double(self) -> None:
        raw = '[[1, 2,], [3,,],]'
        assert parse_llm_json_list(raw) == [[1, 2], [3]]


class TestParseLlmJsonRepairTier:
    """json_repair fallback tier: single quotes, unquoted keys, comments."""

    def test_single_quoted_object(self) -> None:
        raw = "{'done': true, 'reason': 'ok'}"
        assert parse_llm_json_object(raw) == {"done": True, "reason": "ok"}

    def test_single_quoted_python_booleans(self) -> None:
        raw = "{'done': True, 'reason': 'ok'}"
        assert parse_llm_json_object(raw) == {"done": True, "reason": "ok"}

    def test_unquoted_keys(self) -> None:
        raw = '{done: true, reason: "ok"}'
        assert parse_llm_json_object(raw) == {"done": True, "reason": "ok"}

    def test_inline_comments(self) -> None:
        raw = '{"done": true, // verdict\n "reason": "ok"}'
        assert parse_llm_json_object(raw) == {"done": True, "reason": "ok"}

    def test_single_quoted_array(self) -> None:
        raw = "['a', 'b']"
        assert parse_llm_json_list(raw) == ["a", "b"]

    def test_mixed_artifacts_prose_framed(self) -> None:
        raw = "好的，结果为：{'done': true, // 评估\n reason: 'ok'}"
        assert parse_llm_json_object(raw) == {"done": True, "reason": "ok"}

    def test_last_repaired_object_wins(self) -> None:
        raw = "{a: 1} 最终答案：{'done': true}"
        assert parse_llm_json_object(raw) == {"done": True}

    def test_repair_respects_require_key(self) -> None:
        raw = "{a: 1} {'done': true}"
        assert parse_llm_json_object(raw, require_key="done") == {"done": True}
        assert parse_llm_json_object(raw, require_key="missing") is None

    def test_structural_path_still_preferred(self) -> None:
        raw = '{"a": 1} then {"b": 2}'
        assert parse_llm_json_object(raw) == {"b": 2}

    def test_deeply_nested_returns_none_instead_of_crashing(self) -> None:
        depth = 50_000
        raw = '{"a":' * depth + "1" + "}" * depth
        assert parse_llm_json_object(raw) is None

    def test_unclosed_brace_storm_skips_repair(self) -> None:
        raw = "{" * 10_000
        assert parse_llm_json_object(raw) is None
        assert parse_llm_json_list(raw) is None

    def test_unclosed_object_not_treated_as_candidate(self) -> None:
        raw = "{a: 1"  # 无闭合括号 → 非平衡候选，repair 层不处理
        assert parse_llm_json_object(raw) is None

    def test_graceful_degradation_when_dependency_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from myrm_agent_harness.utils import json_parsing as _jp

        monkeypatch.setattr(_jp, "_json_repair_loads", None)
        raw = "{'done': true}"
        assert parse_llm_json_object(raw) is None  # 严格/结构修复均失败 → 降级 None

    def test_single_quote_string_with_many_braces_not_miscounted(self) -> None:
        from myrm_agent_harness.utils.json_parsing import _repair_nesting_depth

        # 单引号字符串内嵌 600 个花括号不应计入嵌套深度
        raw = "{'a': '" + "{" * 600 + "'}"
        assert _repair_nesting_depth(raw) == 1

    def test_single_quoted_brace_inside_string_not_truncated(self) -> None:
        # 单引号字符串内的 } 会被平衡扫描误判为结构闭合，导致候选被截断；
        # 修复后 repair 层必须拿到完整输入，避免静默丢数据。
        raw = "{'a': 'x}y'}"
        assert parse_llm_json_object(raw) == {"a": "x}y"}

    def test_single_quoted_brace_in_leading_value_not_truncated(self) -> None:
        raw = "{'a': 'x}', 'b': 1}"
        assert parse_llm_json_object(raw) == {"a": "x}", "b": 1}

    def test_single_quoted_braces_both_ways_not_truncated(self) -> None:
        raw = "{'a': 'v}1', 'b': 'v{2'}"
        assert parse_llm_json_object(raw) == {"a": "v}1", "b": "v{2"}

    def test_single_quoted_full_prose_not_treated_as_container(self) -> None:
        # 单容器判定必须排除 prose 撇号：整段不是单容器时不得走 repair
        raw = "it's a test {a: 1}"
        assert parse_llm_json_object(raw) == {"a": 1}
        raw2 = "don't worry {'a': 1}"
        assert parse_llm_json_object(raw2) == {"a": 1}

    def test_multi_container_with_single_quotes_still_last_wins(self) -> None:
        raw = "{'a': 1} then {'b': 2}"
        assert parse_llm_json_object(raw) == {"b": 2}
        raw2 = "{'a': 1} and {b: 2}"
        assert parse_llm_json_object(raw2) == {"b": 2}

    def test_fenced_single_quoted_brace_not_truncated(self) -> None:
        # fence 内单引号字符串含 } 同样不能被截断（先前会丢数据）
        raw = "```json\n{'a': 'x}y'}\n```"
        assert parse_llm_json_object(raw) == {"a": "x}y"}

    def test_prose_prefix_single_quoted_brace_not_truncated(self) -> None:
        # prose 前缀 + 单引号字符串含 }：撇号在前言（结构外）不得误开字符串
        raw = "结果是：{'a': 'x}y'}"
        assert parse_llm_json_object(raw) == {"a": "x}y"}
        raw2 = "Here's the result: {'a': 'x}y'}"
        assert parse_llm_json_object(raw2) == {"a": "x}y"}

    def test_apostrophe_outside_container_does_not_swallow_object(self) -> None:
        # 结构外的撇号是 prose，不是字符串开引号，不得吞掉后续对象
        raw = "it's a test {a: 1}"
        assert parse_llm_json_object(raw) == {"a": 1}
        raw2 = "don't worry {'a': 1}"
        assert parse_llm_json_object(raw2) == {"a": 1}
        raw3 = "We're done, {b: 2} see you"
        assert parse_llm_json_object(raw3) == {"b": 2}

    def test_single_quoted_array_with_closing_bracket_in_string(self) -> None:
        # 数组内单引号字符串含 ] 不得截断
        raw = "['a', 'b]x']"
        assert parse_llm_json_list(raw) == ["a", "b]x"]

    def test_nested_single_quoted_braces(self) -> None:
        raw = "{'a': {'b': 'x}y'}}"
        assert parse_llm_json_object(raw) == {"a": {"b": "x}y"}}
        raw2 = "{'a': ['x}y', 'z']}"
        assert parse_llm_json_object(raw2) == {"a": ["x}y", "z"]}


class TestJsonBalanceScanner:
    """平衡扫描器（_iter_json_blocks）的单引号感知语义。

    这些测试锁定扫描器的核心契约：容器内单引号开启字符串（花括号不截断）、
    结构外撇号是 prose（不得吞掉后续对象）、转义与双引号嵌套。
    """

    def test_scan_full_object_single_quoted_braces(self) -> None:
        from myrm_agent_harness.utils import json_parsing as _jp

        assert list(_jp._iter_json_objects("{'a': 'x}y'}")) == ["{'a': 'x}y'}"]

    def test_scan_prose_apostrophe_not_swallow(self) -> None:
        from myrm_agent_harness.utils import json_parsing as _jp

        assert list(_jp._iter_json_objects("it's a test {a: 1}")) == ["{a: 1}"]

    def test_scan_prose_prefix_single_quoted(self) -> None:
        from myrm_agent_harness.utils import json_parsing as _jp

        assert list(_jp._iter_json_objects("结果是：{'a': 'x}y'}")) == ["{'a': 'x}y'}"]

    def test_scan_fenced_single_quoted(self) -> None:
        from myrm_agent_harness.utils import json_parsing as _jp

        assert list(_jp._iter_json_objects("```json\n{'a': 'x}y'}\n```")) == [
            "{'a': 'x}y'}"
        ]

    def test_scan_array_single_quoted_brace(self) -> None:
        from myrm_agent_harness.utils import json_parsing as _jp

        assert list(_jp._iter_json_arrays("['a', 'b]x']")) == ["['a', 'b]x']"]

    def test_scan_escaped_single_quote_in_string(self) -> None:
        from myrm_agent_harness.utils import json_parsing as _jp

        assert list(_jp._iter_json_objects("{'a': 'x\\'y'}")) == ["{'a': 'x\\'y'}"]

    def test_scan_nested_single_quoted(self) -> None:
        from myrm_agent_harness.utils import json_parsing as _jp

        assert list(_jp._iter_json_objects("{'a': {'b': 'x}y'}}")) == [
            "{'a': {'b': 'x}y'}}"
        ]

    def test_scan_double_quote_string_containing_single_quote(self) -> None:
        from myrm_agent_harness.utils import json_parsing as _jp

        assert list(_jp._iter_json_objects('{"a": "it\'s ok", "b": 1}')) == [
            '{"a": "it\'s ok", "b": 1}'
        ]

    def test_scan_multi_container_single_quotes(self) -> None:
        from myrm_agent_harness.utils import json_parsing as _jp

        assert list(_jp._iter_json_objects("{'a': 1} then {'b': 2}")) == [
            "{'a': 1}",
            "{'b': 2}",
        ]

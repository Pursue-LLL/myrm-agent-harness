"""Tests for _close_truncated_json in litellm_utils."""

import json

import pytest

from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
    _close_truncated_json,
)


def _assert_valid_json(text: str) -> object:
    parsed = json.loads(text)
    return parsed


class TestCloseTruncatedJson:
    """Core truncation repair capabilities."""

    def test_empty_input_returns_empty(self) -> None:
        assert _close_truncated_json("") == ""

    def test_valid_json_unchanged(self) -> None:
        original = '{"key": "value"}'
        assert _close_truncated_json(original) == original

    def test_valid_array_unchanged(self) -> None:
        original = '[1, 2, 3]'
        assert _close_truncated_json(original) == original


class TestStackBasedClosing:
    """Bug fix: stack instead of counters for correct nesting order."""

    def test_mixed_nesting_object_in_array(self) -> None:
        result = _close_truncated_json('[{"a": 1, "b": [{"c": 2')
        parsed = _assert_valid_json(result)
        assert parsed == [{"a": 1, "b": [{"c": 2}]}]

    def test_array_in_object(self) -> None:
        result = _close_truncated_json('{"items": [1, 2, 3')
        parsed = _assert_valid_json(result)
        assert parsed == {"items": [1, 2, 3]}

    def test_deeply_nested_objects(self) -> None:
        result = _close_truncated_json('{"a": {"b": {"c": {"d": 1')
        parsed = _assert_valid_json(result)
        assert parsed == {"a": {"b": {"c": {"d": 1}}}}

    def test_pure_nested_arrays(self) -> None:
        result = _close_truncated_json('[1, 2, [3, 4')
        parsed = _assert_valid_json(result)
        assert parsed == [1, 2, [3, 4]]

    def test_three_level_mixed(self) -> None:
        result = _close_truncated_json('{"a": [{"b": [{"c": 1')
        parsed = _assert_valid_json(result)
        assert parsed == {"a": [{"b": [{"c": 1}]}]}

    def test_single_open_brace(self) -> None:
        result = _close_truncated_json("{")
        _assert_valid_json(result)
        assert result == "{}"

    def test_single_open_bracket(self) -> None:
        result = _close_truncated_json("[")
        _assert_valid_json(result)
        assert result == "[]"

    def test_empty_structures_mixed(self) -> None:
        result = _close_truncated_json('{"a":[],"b":{},"c":[{')
        parsed = _assert_valid_json(result)
        assert parsed == {"a": [], "b": {}, "c": [{}]}


class TestDanglingKeyNullFill:
    """Bug fix: fill dangling key with null."""

    def test_simple_dangling_key(self) -> None:
        result = _close_truncated_json('{"content":')
        parsed = _assert_valid_json(result)
        assert parsed == {"content": None}

    def test_dangling_key_with_prior_field(self) -> None:
        result = _close_truncated_json('{"path": "/foo", "content":')
        parsed = _assert_valid_json(result)
        assert parsed == {"path": "/foo", "content": None}

    def test_dangling_key_after_comma(self) -> None:
        result = _close_truncated_json('{"a": 1, "b":')
        parsed = _assert_valid_json(result)
        assert parsed == {"a": 1, "b": None}

    def test_nested_dangling_key(self) -> None:
        result = _close_truncated_json('{"a": {"b":')
        parsed = _assert_valid_json(result)
        assert parsed == {"a": {"b": None}}

    def test_deeply_nested_dangling_key(self) -> None:
        result = _close_truncated_json('{"a": {"b": {"c": {"d":')
        parsed = _assert_valid_json(result)
        assert parsed == {"a": {"b": {"c": {"d": None}}}}


class TestLiteralCompletion:
    """Truncated JSON literals (true/false/null) completion."""

    @pytest.mark.parametrize(
        ("input_text", "expected_value"),
        [
            ('{"flag": t', True),
            ('{"flag": tr', True),
            ('{"flag": tru', True),
            ('{"flag": true', True),
        ],
    )
    def test_truncated_true(self, input_text: str, expected_value: bool) -> None:
        result = _close_truncated_json(input_text)
        parsed = _assert_valid_json(result)
        assert parsed["flag"] is expected_value

    @pytest.mark.parametrize(
        ("input_text", "expected_value"),
        [
            ('{"active": f', False),
            ('{"active": fa', False),
            ('{"active": fal', False),
            ('{"active": fals', False),
            ('{"active": false', False),
        ],
    )
    def test_truncated_false(self, input_text: str, expected_value: bool) -> None:
        result = _close_truncated_json(input_text)
        parsed = _assert_valid_json(result)
        assert parsed["active"] is expected_value

    @pytest.mark.parametrize(
        ("input_text",),
        [
            ('{"val": n',),
            ('{"val": nu',),
            ('{"val": nul',),
            ('{"val": null',),
        ],
    )
    def test_truncated_null(self, input_text: str) -> None:
        result = _close_truncated_json(input_text)
        parsed = _assert_valid_json(result)
        assert parsed["val"] is None

    def test_literal_in_array(self) -> None:
        result = _close_truncated_json("[1, tru")
        parsed = _assert_valid_json(result)
        assert parsed == [1, True]

    def test_null_in_array(self) -> None:
        result = _close_truncated_json('["a", nul')
        parsed = _assert_valid_json(result)
        assert parsed == ["a", None]

    def test_literal_like_string_not_affected(self) -> None:
        result = _close_truncated_json('{"name": "tru')
        parsed = _assert_valid_json(result)
        assert parsed == {"name": "tru"}


class TestTrailingBackslash:
    """Odd trailing backslashes stripped to avoid escaping the closing quote."""

    def test_single_trailing_backslash(self) -> None:
        result = _close_truncated_json('{"msg": "test\\')
        _assert_valid_json(result)

    def test_even_trailing_backslashes_preserved(self) -> None:
        result = _close_truncated_json('{"msg": "test\\\\')
        parsed = _assert_valid_json(result)
        assert parsed["msg"].endswith("\\")

    def test_url_with_colon_in_string(self) -> None:
        result = _close_truncated_json('{"url": "http://example.com:80')
        parsed = _assert_valid_json(result)
        assert parsed["url"] == "http://example.com:80"


class TestNumericTruncation:
    """Truncated numeric values: scientific notation, trailing dot, bare minus."""

    def test_lowercase_e(self) -> None:
        result = _close_truncated_json('{"val": 1.5e')
        parsed = _assert_valid_json(result)
        assert parsed["val"] == pytest.approx(1.5)

    def test_uppercase_e(self) -> None:
        result = _close_truncated_json('{"val": 1.5E')
        parsed = _assert_valid_json(result)
        assert parsed["val"] == pytest.approx(1.5)

    def test_e_with_plus(self) -> None:
        result = _close_truncated_json('{"val": 1.5e+')
        parsed = _assert_valid_json(result)
        assert parsed["val"] == pytest.approx(1.5)

    def test_e_with_minus(self) -> None:
        result = _close_truncated_json('{"val": 1.5E-')
        parsed = _assert_valid_json(result)
        assert parsed["val"] == pytest.approx(1.5)

    def test_trailing_dot(self) -> None:
        result = _close_truncated_json('{"x": 0.')
        parsed = _assert_valid_json(result)
        assert parsed["x"] == pytest.approx(0.0)

    def test_bare_minus(self) -> None:
        result = _close_truncated_json('{"x": -')
        _assert_valid_json(result)

    def test_bare_minus_after_comma(self) -> None:
        result = _close_truncated_json('{"a": 1, "b": -')
        parsed = _assert_valid_json(result)
        assert parsed["a"] == 1

    def test_integer_preserved(self) -> None:
        result = _close_truncated_json('{"x": 42')
        parsed = _assert_valid_json(result)
        assert parsed["x"] == 42


class TestTrailingComma:
    """Trailing comma removal."""

    def test_trailing_comma_in_object(self) -> None:
        result = _close_truncated_json('{"a": 1, "b": 2,')
        parsed = _assert_valid_json(result)
        assert parsed == {"a": 1, "b": 2}

    def test_trailing_comma_in_array(self) -> None:
        result = _close_truncated_json("[1, 2, 3,")
        parsed = _assert_valid_json(result)
        assert parsed == [1, 2, 3]


class TestUnterminatedString:
    """Unterminated strings are closed."""

    def test_simple_unterminated(self) -> None:
        result = _close_truncated_json('{"text": "hello world')
        parsed = _assert_valid_json(result)
        assert parsed == {"text": "hello world"}

    def test_string_with_escaped_quote(self) -> None:
        result = _close_truncated_json('{"msg": "he said \\"hello')
        parsed = _assert_valid_json(result)
        assert "hello" in parsed["msg"]

    def test_array_string_element(self) -> None:
        result = _close_truncated_json('{"tags": ["foo", "bar')
        parsed = _assert_valid_json(result)
        assert parsed == {"tags": ["foo", "bar"]}


class TestEdgeCases:
    """Additional edge cases for complete coverage."""

    def test_whitespace_only_input(self) -> None:
        result = _close_truncated_json("   ")
        assert result == ""

    def test_empty_key_dangling(self) -> None:
        result = _close_truncated_json('{"":')
        parsed = _assert_valid_json(result)
        assert parsed[""] is None

    def test_key_with_colon_in_name(self) -> None:
        result = _close_truncated_json('{"host:port":')
        parsed = _assert_valid_json(result)
        assert parsed["host:port"] is None

    def test_colon_then_space_only(self) -> None:
        result = _close_truncated_json('{"key": ')
        parsed = _assert_valid_json(result)
        assert parsed == {"key": None}

    def test_multiple_fields_second_cut(self) -> None:
        result = _close_truncated_json('{"a": 1, "b": "hello')
        parsed = _assert_valid_json(result)
        assert parsed == {"a": 1, "b": "hello"}

    def test_third_field_dangling(self) -> None:
        result = _close_truncated_json('{"a": 1, "b": 2, "c":')
        parsed = _assert_valid_json(result)
        assert parsed == {"a": 1, "b": 2, "c": None}

    def test_array_string_element(self) -> None:
        result = _close_truncated_json('["hello')
        parsed = _assert_valid_json(result)
        assert parsed == ["hello"]

    def test_array_mixed_types(self) -> None:
        result = _close_truncated_json('[1, "two", tru')
        parsed = _assert_valid_json(result)
        assert parsed == [1, "two", True]

    def test_array_of_arrays(self) -> None:
        result = _close_truncated_json("[[1,2],[3,4],[5")
        parsed = _assert_valid_json(result)
        assert parsed == [[1, 2], [3, 4], [5]]

    def test_array_of_objects(self) -> None:
        result = _close_truncated_json('[{"a":1},{"b":')
        parsed = _assert_valid_json(result)
        assert parsed[0] == {"a": 1}

    def test_escaped_backslash_pair(self) -> None:
        result = _close_truncated_json('{"path": "C:\\\\\\\\')
        _assert_valid_json(result)

    def test_trailing_spaces_preserved(self) -> None:
        result = _close_truncated_json('{"key": "val"   ')
        parsed = _assert_valid_json(result)
        assert parsed == {"key": "val"}

    def test_nested_empty_structures(self) -> None:
        original = '{"a": {}, "b": []}'
        assert _close_truncated_json(original) == original

    def test_complete_null_value(self) -> None:
        original = '{"a": null}'
        assert _close_truncated_json(original) == original

    def test_complete_bool_values(self) -> None:
        original = '{"t": true, "f": false}'
        assert _close_truncated_json(original) == original


class TestPipelineIntegration:
    """Verify _close_truncated_json works correctly via the recovery pipeline."""

    def test_dangling_key_via_pipeline(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            parse_tool_call_arguments_with_recovery,
        )

        result = parse_tool_call_arguments_with_recovery(
            '{"action": "write", "content":',
            "edit_file",
        )
        assert result is not None
        assert result.args["action"] == "write"
        assert result.args["content"] is None

    def test_truncated_literal_via_pipeline(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            parse_tool_call_arguments_with_recovery,
        )

        result = parse_tool_call_arguments_with_recovery(
            '{"enabled": tru',
            "toggle",
        )
        assert result is not None
        assert result.args["enabled"] is True


class TestRecoveryPipelineBranches:
    """Cover additional recovery strategies and helper functions."""

    def test_resolve_parameters_schema_direct(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            _resolve_parameters_schema,
        )

        schema = {"parameters": {"type": "object", "properties": {"a": {"type": "string"}}}}
        result = _resolve_parameters_schema(schema)
        assert result is not None
        assert "properties" in result

    def test_resolve_parameters_schema_none(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            _resolve_parameters_schema,
        )

        assert _resolve_parameters_schema(None) is None
        assert _resolve_parameters_schema({"parameters": "bad"}) is None

    def test_regex_fallback_extract_with_schema(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            _regex_fallback_extract,
        )

        schema = {
            "function": {
                "name": "tool",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "count": {"type": "integer"},
                    },
                },
            }
        }
        text = 'some garbage "path": "/foo/bar" more "count": 42 end'
        result = _regex_fallback_extract(text, schema)
        assert result["path"] == "/foo/bar"
        assert result["count"] == 42

    def test_regex_fallback_extract_boolean_null(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            _regex_fallback_extract,
        )

        schema = {
            "function": {
                "name": "tool",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "flag": {"type": "boolean"},
                        "val": {"type": "string"},
                    },
                },
            }
        }
        text = 'err "flag": true "val": null done'
        result = _regex_fallback_extract(text, schema)
        assert result["flag"] is True
        assert result["val"] is None

    def test_regex_fallback_extract_float(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            _regex_fallback_extract,
        )

        schema = {
            "function": {
                "name": "tool",
                "parameters": {
                    "type": "object",
                    "properties": {"score": {"type": "number"}},
                },
            }
        }
        text = '"score": 3.14'
        result = _regex_fallback_extract(text, schema)
        assert result["score"] == pytest.approx(3.14)

    def test_regex_fallback_without_schema(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            _regex_fallback_extract,
        )

        text = '"command": "ls -la" "path": "/tmp"'
        result = _regex_fallback_extract(text, None)
        assert result["command"] == "ls -la"
        assert result["path"] == "/tmp"

    def test_regex_fallback_embedded_quotes(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            _regex_fallback_extract,
        )

        schema = {
            "function": {
                "name": "tool",
                "parameters": {
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                },
            }
        }
        text = '"content": "print(hello) world"'
        result = _regex_fallback_extract(text, schema)
        assert "hello" in result.get("content", "")

    def test_is_safe_degraded_empty(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            _is_safe_degraded_result,
        )

        assert _is_safe_degraded_result({}, None) is False

    def test_is_safe_degraded_with_required(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            _is_safe_degraded_result,
        )

        schema = {
            "function": {
                "name": "tool",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        }
        assert _is_safe_degraded_result({"path": "/foo"}, schema) is True
        assert _is_safe_degraded_result({"other": "val"}, schema) is False

    def test_is_safe_degraded_no_schema(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            _is_safe_degraded_result,
        )

        assert _is_safe_degraded_result({"key": "val"}, None) is True
        assert _is_safe_degraded_result({"command": "rm -rf"}, None) is False

    def test_extract_json_from_malformed_response(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            extract_json_from_malformed_response,
        )

        raw = '{"path": "demo.py", "content": "hello"}extra_junk]'
        result = extract_json_from_malformed_response(raw)
        assert result == {"path": "demo.py", "content": "hello"}

    def test_clean_model_kwargs_removes_internal_keys(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            clean_model_kwargs,
        )

        kwargs = {"temperature": 0.7, "_in_fallback": True, "_json_mode_fallback": True}
        result = clean_model_kwargs(kwargs, "gpt-4")
        assert "_in_fallback" not in result
        assert result["temperature"] == 0.7

    def test_clean_model_kwargs_kimi_temperature_floor(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            clean_model_kwargs,
        )

        kwargs = {"temperature": 0.5}
        result = clean_model_kwargs(kwargs, "moonshot/kimi-k2.5")
        assert result["temperature"] == 1.0

    def test_clean_model_kwargs_skips_response_format(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            clean_model_kwargs,
        )

        kwargs = {"temperature": 0.7, "response_format": {"type": "json_object"}}
        result = clean_model_kwargs(kwargs, "qwen-plus")
        assert "response_format" not in result

    def test_pipeline_failed_recovery(self) -> None:
        from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
            parse_tool_call_arguments_with_recovery,
        )

        result = parse_tool_call_arguments_with_recovery(
            "completely unparseable garbage !@#$%",
            "unknown_tool",
        )
        assert result.strategy == "failed"
        assert result.degraded is True

import myrm_agent_harness.toolkits.mcp.schema.coerce as schema_coerce_module
from myrm_agent_harness.toolkits.mcp.schema import (
    coerce_arguments_by_schema,
    coerce_value,
    get_schema_coercion_stats,
    prepare_mcp_call_arguments,
    reset_schema_coercion_stats,
)

# ---------------------------------------------------------------------------
# Argument coercion tests
# ---------------------------------------------------------------------------


def test_coerce_arguments_by_schema_array():
    schema = {"properties": {"files": {"type": "array", "items": {"type": "string"}}}}

    # Simulate LLM outputting a stringified JSON array
    kwargs = {"files": '["main.py", "utils.py"]'}

    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert isinstance(coerced["files"], list)
    assert coerced["files"] == ["main.py", "utils.py"]


def test_coerce_arguments_by_schema_object():
    schema = {"properties": {"metadata": {"type": "object"}}}

    kwargs = {"metadata": "{'key': 'value'}"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert isinstance(coerced["metadata"], dict)
    assert coerced["metadata"]["key"] == "value"


def test_coerce_arguments_no_schema():
    kwargs = {"key": "value"}
    assert coerce_arguments_by_schema(None, kwargs) == kwargs
    assert coerce_arguments_by_schema({}, kwargs) == kwargs


def test_coerce_arguments_markdown_stripping():
    schema = {"properties": {"files": {"type": "array"}}}
    kwargs = {"files": '```json\n["main.py"]\n```'}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["files"] == ["main.py"]


def test_coerce_arguments_boolean():
    schema = {"properties": {"dry_run": {"type": "boolean"}, "force": {"type": "boolean"}}}
    kwargs = {"dry_run": "true", "force": "False"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["dry_run"] is True
    assert coerced["force"] is False


def test_coerce_arguments_number():
    schema = {"properties": {"limit": {"type": "integer"}, "threshold": {"type": "number"}}}
    kwargs = {"limit": "10", "threshold": "3.14"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["limit"] == 10
    assert isinstance(coerced["limit"], int)
    assert coerced["threshold"] == 3.14
    assert isinstance(coerced["threshold"], float)


def test_coerce_number_big_integer_preserves_precision():
    """number schema with a pure-integer literal must keep full precision (int)."""
    big_id = "9007199254740993"  # 2**53 + 1 — float() would round to ...992.0
    schema = {"properties": {"id": {"type": "number"}}}
    coerced = coerce_arguments_by_schema(schema, {"id": big_id})
    assert coerced["id"] == 9007199254740993
    assert isinstance(coerced["id"], int)


def test_coerce_number_big_integer_negative_preserves_precision():
    schema = {"properties": {"delta": {"type": "number"}}}
    coerced = coerce_arguments_by_schema(schema, {"delta": "-9007199254740993"})
    assert coerced["delta"] == -9007199254740993
    assert isinstance(coerced["delta"], int)


def test_coerce_number_decimal_and_exponent_still_float():
    """Decimal forms stay float; integral exponent forms preserve exactness as int.

    ``"1e10"`` parses exactly via Decimal to 10000000000, so coercing it to
    ``int`` preserves precision (and serializes without a trailing ``.0`` that
    strict APIs reject), while non-integral decimals like ``"3.14"`` coerce to
    ``float``.
    """
    schema = {"properties": {"a": {"type": "number"}, "b": {"type": "number"}}}
    coerced = coerce_arguments_by_schema(schema, {"a": "3.14", "b": "1e10"})
    assert coerced["a"] == 3.14
    assert isinstance(coerced["a"], float)
    assert coerced["b"] == 10000000000
    assert isinstance(coerced["b"], int)


def test_coerce_integer_float_form_literal_to_int():
    """integer schema with a float-form literal denoting a whole number → int.

    Mirrors openclaw's Number.isInteger behavior: "25.0" → 25. int() alone
    would raise ValueError and leave the raw string.
    """
    schema = {"properties": {"count": {"type": "integer"}}}
    coerced = coerce_arguments_by_schema(schema, {"count": "25.0"})
    assert coerced["count"] == 25
    assert isinstance(coerced["count"], int)


def test_coerce_integer_exponent_form_literal_to_int():
    """integer schema with an exponent literal denoting a whole number → int."""
    schema = {"properties": {"count": {"type": "integer"}}}
    coerced = coerce_arguments_by_schema(schema, {"count": "1e3"})
    assert coerced["count"] == 1000
    assert isinstance(coerced["count"], int)


def test_coerce_number_float_form_big_integer_preserves_precision():
    """number schema with a float-form literal of a big integer → exact int.

    "9007199254740993.0" must not round through float() (which yields
    ...992.0); Decimal parsing keeps the exact integer.
    """
    schema = {"properties": {"id": {"type": "number"}}}
    coerced = coerce_arguments_by_schema(schema, {"id": "9007199254740993.0"})
    assert coerced["id"] == 9007199254740993
    assert isinstance(coerced["id"], int)


def test_coerce_integer_fractional_literal_keeps_string():
    """integer schema with a genuinely fractional literal keeps the string.

    Mirrors openclaw's Number.isInteger rejection for non-integers.
    """
    schema = {"properties": {"count": {"type": "integer"}}}
    coerced = coerce_arguments_by_schema(schema, {"count": "25.5"})
    assert coerced["count"] == "25.5"


def test_coerce_integer_invalid_numeric_literal_keeps_string():
    """Unparseable numeric literals (hex, garbage) stay untouched."""
    schema = {"properties": {"count": {"type": "integer"}}}
    for raw in ("0x10", "abc", "nan", "inf"):
        coerced = coerce_arguments_by_schema(schema, {"count": raw})
        assert coerced["count"] == raw, raw


def test_coerce_number_non_finite_keeps_string():
    """inf / nan are not valid JSON numbers — keep the string.

    Mirrors openclaw's Number.isFinite guard: Number("1e100000") → Infinity
    fails the finite check and the raw string is preserved.
    """
    schema = {"properties": {"v": {"type": "number"}}}
    for raw in ("inf", "-inf", "nan", "Infinity", "1e100000"):
        coerced = coerce_arguments_by_schema(schema, {"v": raw})
        assert coerced["v"] == raw, raw


def test_coerce_number_huge_exponent_integer_stays_string():
    """Exponent literals whose integer value exceeds int_max_str_digits stay strings.

    int(Decimal("1e100000")) would materialize a 100001-digit int (memory DoS)
    and bypass Python's int_max_str_digits guard — we enforce the same limit.
    """
    schema = {"properties": {"v": {"type": "number"}}}
    coerced = coerce_arguments_by_schema(schema, {"v": "1e100000"})
    assert coerced["v"] == "1e100000"


def test_coerce_arguments_recursive():
    schema = {
        "properties": {
            "filters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "tags": {"type": "array", "items": {"type": "boolean"}},
                },
            }
        }
    }
    # LLM hallucinates stringified integer and boolean inside a nested object
    kwargs = {"filters": {"limit": "42", "tags": ["true", "False"]}}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["filters"]["limit"] == 42
    assert coerced["filters"]["tags"] == [True, False]


def test_coerce_arguments_injects_null_for_missing_required_nullable():
    schema = {
        "type": "object",
        "properties": {
            "captureTransform": {"type": ["object", "null"]},
            "annotations": {"type": ["object", "null"]},
            "bShowUI": {"type": "boolean"},
        },
        "required": ["captureTransform", "annotations", "bShowUI"],
    }
    kwargs = {"bShowUI": False}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["bShowUI"] is False
    assert coerced["captureTransform"] is None
    assert coerced["annotations"] is None


def test_coerce_arguments_does_not_inject_non_nullable_required():
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["path", "limit"],
    }
    kwargs = {"path": "README.md"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert "limit" not in coerced


def test_coerce_arguments_union_object_from_json_string():
    schema = {"properties": {"payload": {"type": ["object", "null"]}}}
    kwargs = {"payload": '{"name": "demo"}'}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["payload"] == {"name": "demo"}


def test_coerce_arguments_union_array_from_json_string():
    schema = {"properties": {"items": {"type": ["array", "null"], "items": {"type": "string"}}}}
    kwargs = {"items": '["a", "b"]'}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["items"] == ["a", "b"]


def test_coerce_arguments_union_null_string_to_none():
    schema = {"properties": {"payload": {"type": ["object", "null"]}}}
    kwargs = {"payload": "null"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["payload"] is None


def test_coerce_arguments_mixed_union_prefers_container_literal():
    schema = {
        "properties": {
            "payload": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "object"},
                    {"type": "null"},
                ]
            }
        }
    }
    kwargs = {"payload": '{"x": 1}'}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["payload"] == {"x": 1}


def test_coerce_arguments_mixed_union_keeps_plain_string():
    schema = {
        "properties": {
            "payload": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "object"},
                    {"type": "null"},
                ]
            }
        }
    }
    kwargs = {"payload": "hello world"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["payload"] == "hello world"


def test_coerce_arguments_mixed_union_incomplete_container_keeps_string():
    schema = {
        "properties": {
            "payload": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "object"},
                    {"type": "null"},
                ]
            }
        }
    }
    kwargs = {"payload": "{"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["payload"] == "{"


def test_coerce_arguments_array_from_ast_literal_single_quotes():
    schema = {"properties": {"items": {"type": "array", "items": {"type": "string"}}}}
    kwargs = {"items": "['a', 'b']"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["items"] == ["a", "b"]


def test_coerce_array_bare_string_wrapped_single_element():
    """Bare string for an array schema wraps into a single-element list.

    Mirrors hermes-agent: open-weight models emit ``{"urls": "https://a.com"}``
    when the tool expects ``urls: array<string>``.
    """
    schema = {"properties": {"urls": {"type": "array", "items": {"type": "string"}}}}
    coerced = coerce_arguments_by_schema(schema, {"urls": "https://a.com"})
    assert coerced["urls"] == ["https://a.com"]


def test_coerce_array_bare_int_wrapped_single_element():
    """Bare non-string scalar for an array schema wraps too."""
    schema = {"properties": {"nums": {"type": "array", "items": {"type": "integer"}}}}
    coerced = coerce_arguments_by_schema(schema, {"nums": 5})
    assert coerced["nums"] == [5]


def test_coerce_array_already_list_untouched():
    """Existing list for an array schema stays as-is."""
    schema = {"properties": {"nums": {"type": "array", "items": {"type": "integer"}}}}
    coerced = coerce_arguments_by_schema(schema, {"nums": [1, 2, 3]})
    assert coerced["nums"] == [1, 2, 3]


def test_coerce_array_null_not_wrapped():
    """None stays None — wrapping [] would hide the model's 'omit' intent."""
    schema = {"properties": {"urls": {"type": ["array", "null"], "items": {"type": "string"}}}}
    coerced = coerce_arguments_by_schema(schema, {"urls": None})
    assert coerced["urls"] is None


def test_coerce_array_union_accepting_string_not_wrapped():
    """Union array|string: a string already satisfies the schema — no wrap."""
    schema = {"properties": {"value": {"type": ["array", "string"]}}}
    coerced = coerce_arguments_by_schema(schema, {"value": "single"})
    assert coerced["value"] == "single"


def test_coerce_array_json_array_string_parsed_then_items_coerced():
    """JSON-encoded array strings still parse; items coerce via items schema."""
    schema = {"properties": {"items": {"type": "array", "items": {"type": "integer"}}}}
    coerced = coerce_arguments_by_schema(schema, {"items": "[1, '2']"})
    assert coerced["items"] == [1, 2]


def test_coerce_array_wrapped_item_coerced_by_items_schema():
    """Wrapped single element is recursively coerced by the items schema."""
    schema = {"properties": {"counts": {"type": "array", "items": {"type": "integer"}}}}
    coerced = coerce_arguments_by_schema(schema, {"counts": "3"})
    assert coerced["counts"] == [3]
    assert isinstance(coerced["counts"][0], int)


def test_coerce_array_markdown_wrapped_failed_container_string():
    """Markdown-wrapped container strings wrap identically to bare ones.

    The wrapping heuristic must judge the markdown-stripped value, otherwise a
    ````` ```json [abc ``` ```` value is wrapped without the parse-failure
    warning that a bare ``[abc`` triggers — inconsistent behavior.
    """
    schema = {"properties": {"items": {"type": "array", "items": {"type": "string"}}}}
    bare = coerce_arguments_by_schema(schema, {"items": "[abc"})
    markdown = coerce_arguments_by_schema(schema, {"items": "```json\n[abc\n```"})
    assert bare["items"] == ["[abc"]
    assert markdown["items"] == ["[abc"]
    assert bare == markdown


def test_coerce_array_markdown_wrapped_valid_json_parsed():
    """Markdown-wrapped valid JSON arrays still parse to native lists."""
    schema = {"properties": {"items": {"type": "array", "items": {"type": "string"}}}}
    coerced = coerce_arguments_by_schema(schema, {"items": "```json\n[\"a\", \"b\"]\n```"})
    assert coerced["items"] == ["a", "b"]


def test_coerce_boolean_from_int_one_zero():
    """int 1/0 → boolean for boolean schemas (openclaw bidirectional)."""
    schema = {"properties": {"enabled": {"type": "boolean"}}}
    assert coerce_arguments_by_schema(schema, {"enabled": 1})["enabled"] is True
    assert coerce_arguments_by_schema(schema, {"enabled": 0})["enabled"] is False


def test_coerce_boolean_from_float_one_zero():
    """Float forms 1.0/0.0 → boolean, matching openclaw's typeof number check."""
    schema = {"properties": {"enabled": {"type": "boolean"}}}
    assert coerce_arguments_by_schema(schema, {"enabled": 1.0})["enabled"] is True
    assert coerce_arguments_by_schema(schema, {"enabled": 0.0})["enabled"] is False


def test_coerce_int_from_boolean():
    """boolean → int 1/0 for integer/number schemas (openclaw bidirectional)."""
    schema = {"properties": {"max": {"type": "integer"}, "ratio": {"type": "number"}}}
    assert coerce_arguments_by_schema(schema, {"max": True, "ratio": False}) == {"max": 1, "ratio": 0}


def test_coerce_boolean_int_outside_01_untouched():
    """int outside {0,1} is never silently converted to boolean."""
    schema = {"properties": {"enabled": {"type": "boolean"}}}
    assert coerce_arguments_by_schema(schema, {"enabled": 5})["enabled"] == 5


def test_coerce_boolean_union_int_accepted_not_converted():
    """Union boolean|integer: an int already satisfies the schema — no flip."""
    schema = {"properties": {"flag": {"type": ["boolean", "integer"]}}}
    assert coerce_arguments_by_schema(schema, {"flag": 1})["flag"] == 1


def test_coerce_boolean_native_bool_untouched():
    """Native True/False for boolean schemas stays as-is."""
    schema = {"properties": {"enabled": {"type": "boolean"}}}
    assert coerce_arguments_by_schema(schema, {"enabled": True})["enabled"] is True
    assert coerce_arguments_by_schema(schema, {"enabled": False})["enabled"] is False


def test_coerce_json_string_over_length_limit_not_parsed():
    """>64KB JSON container strings skip parsing (CPU/memory DoS guard)."""
    schema = {"properties": {"payload": {"type": ["object", "null"]}}}
    huge = "{" + "x" * (64 * 1024 + 10) + "}"
    coerced = coerce_arguments_by_schema(schema, {"payload": huge})
    assert coerced["payload"] == huge


def test_coerce_array_over_length_not_wrapped():
    """>64KB container-like strings aren't wrapped into a single-element list."""
    schema = {"properties": {"items": {"type": "array"}}}
    huge = "[" + "x" * (64 * 1024 + 10) + "]"
    coerced = coerce_arguments_by_schema(schema, {"items": huge})
    assert coerced["items"] == huge


def test_coerce_arguments_object_invalid_literal_keeps_string():
    schema = {"properties": {"payload": {"type": "object"}}}
    kwargs = {"payload": "{'x':"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["payload"] == "{'x':"


def test_coerce_arguments_string_reverse_coercion_paths():
    schema = {"properties": {"payload": {"type": "string"}}}
    coerced_dict = coerce_arguments_by_schema(schema, {"payload": {"k": "v"}})
    coerced_num = coerce_arguments_by_schema(schema, {"payload": 42})
    coerced_list = coerce_arguments_by_schema(schema, {"payload": [1, 2]})
    assert coerced_dict["payload"] == '{"k": "v"}'
    assert coerced_num["payload"] == "42"
    assert coerced_list["payload"] == "[1, 2]"


def test_coerce_arguments_preserves_unknown_key_passthrough():
    schema = {"properties": {"known": {"type": "string"}}}
    kwargs = {"known": "ok", "extra": 123}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["extra"] == 123


def test_internal_value_conforms_to_schema_types_branches():
    schema = {
        "type": [
            "string",
            "object",
            "array",
            "integer",
            "number",
            "boolean",
            "null",
        ]
    }
    assert schema_coerce_module._value_conforms_to_schema_types(schema, None) is True
    assert schema_coerce_module._value_conforms_to_schema_types(schema, True) is True
    assert schema_coerce_module._value_conforms_to_schema_types(schema, {"x": 1}) is True
    assert schema_coerce_module._value_conforms_to_schema_types(schema, ["x"]) is True
    assert schema_coerce_module._value_conforms_to_schema_types(schema, 1) is True
    assert schema_coerce_module._value_conforms_to_schema_types(schema, 1.5) is True
    assert schema_coerce_module._value_conforms_to_schema_types(schema, "x") is True


def test_coerce_value_non_dict_schema_passthrough():
    assert schema_coerce_module.coerce_value("not-a-schema", "value") == "value"


def test_coerce_arguments_nullable_true_injects_missing_required():
    schema = {
        "type": "object",
        "properties": {
            "opt": {"type": "object", "nullable": True},
            "name": {"type": "string"},
        },
        "required": ["opt", "name"],
    }
    kwargs = {"name": "demo"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["name"] == "demo"
    assert coerced["opt"] is None


def test_coerce_arguments_nullable_true_null_string_to_none():
    schema = {
        "type": "object",
        "properties": {
            "opt": {"type": "object", "nullable": True},
        },
    }
    kwargs = {"opt": "null"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["opt"] is None


def test_coerce_arguments_anyof_enum_null_injects_missing_required():
    schema = {
        "type": "object",
        "properties": {
            "opt": {
                "anyOf": [
                    {"type": "object"},
                    {"enum": [None]},
                ]
            },
            "name": {"type": "string"},
        },
        "required": ["opt", "name"],
    }
    kwargs = {"name": "demo"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["name"] == "demo"
    assert coerced["opt"] is None


def test_coerce_arguments_const_null_injects_missing_required():
    schema = {
        "type": "object",
        "properties": {
            "opt": {"const": None},
            "name": {"type": "string"},
        },
        "required": ["opt", "name"],
    }
    kwargs = {"name": "demo"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["name"] == "demo"
    assert coerced["opt"] is None


def test_coerce_arguments_type_guard_rejects_scalar_for_object():
    schema = {"properties": {"payload": {"type": ["object", "null"]}}}
    kwargs = {"payload": "123"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    # Keep the original scalar string when schema expects object.
    assert coerced["payload"] == "123"


def test_primary_non_null_type_all_null():
    """_primary_non_null_type returns None when only null types declared (L240)."""
    schema = {"type": "null"}
    result = coerce_arguments_by_schema(
        {"type": "object", "properties": {"x": schema}, "required": ["x"]},
        {},
    )
    assert result == {"x": None}


def test_value_conforms_unknown_type():
    """_value_conforms_to_schema_types returns False for unsupported types (L264)."""
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    result = coerce_arguments_by_schema(schema, {"x": b"bytes_value"})
    assert result["x"] == b"bytes_value"


def test_coerce_dict_to_string_via_name_key():
    """Reverse coercion extracts string via name/value/text/id keys (L350-352)."""
    schema = {"type": "string"}
    result = coerce_value(schema, {"name": "Tokyo Station", "code": "TYO"})
    assert result == "Tokyo Station"


def test_coerce_dict_to_string_via_value_key():
    """Reverse coercion uses 'value' key when 'name' absent."""
    schema = {"type": "string"}
    result = coerce_value(schema, {"value": "hello", "meta": 123})
    assert result == "hello"


def test_coerce_dict_to_string_via_text_key():
    """Reverse coercion uses 'text' key."""
    schema = {"type": "string"}
    result = coerce_value(schema, {"text": "world", "idx": 1})
    assert result == "world"


def test_coerce_dict_to_string_via_id_key():
    """Reverse coercion uses 'id' key."""
    schema = {"type": "string"}
    result = coerce_value(schema, {"id": "abc-123", "data": {}})
    assert result == "abc-123"


def test_coerce_arguments_empty_properties():
    """coerce_arguments_by_schema returns kwargs unmodified when properties is empty (L397)."""
    schema = {"type": "object", "properties": {}}
    result = coerce_arguments_by_schema(schema, {"a": 1, "b": "two"})
    assert result == {"a": 1, "b": "two"}


def test_coerce_value_null_only_schema_string_passthrough():
    """coerce_value with type:null schema leaves non-null string unchanged (L240)."""
    schema = {"type": "null"}
    result = coerce_value(schema, "some_string")
    assert result == "some_string"


# ---------------------------------------------------------------------------
# Coercion observability counters
# ---------------------------------------------------------------------------


def test_schema_coercion_stats_tracks_core_events():
    reset_schema_coercion_stats()
    schema = {
        "type": "object",
        "properties": {
            "opt": {"type": "object", "nullable": True},
            "payload": {"type": ["object", "null"]},
            "name": {"type": "string"},
        },
        "required": ["opt", "name"],
    }
    kwargs = {
        "name": "demo",
        "payload": "123",
    }
    _ = coerce_arguments_by_schema(schema, kwargs)
    stats = get_schema_coercion_stats()
    assert stats["coerce_argument_calls"] >= 1
    assert stats["required_nullable_null_injections"] >= 1
    assert stats["json_type_guard_rejections"] >= 1


def test_schema_coercion_stats_tracks_ast_type_guard_rejection():
    reset_schema_coercion_stats()
    schema = {"properties": {"payload": {"type": ["object", "null"]}}}
    kwargs = {"payload": "True"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    stats = get_schema_coercion_stats()
    assert coerced["payload"] == "True"
    assert stats["coerce_argument_calls"] >= 1
    assert stats["ast_type_guard_rejections"] >= 1


def test_schema_coercion_stats_tracks_array_wrap_and_bool_cross():
    """New counters: bare-scalar array wraps and 1/0↔boolean cross-coercions."""
    reset_schema_coercion_stats()
    coerce_arguments_by_schema(
        {"properties": {"labels": {"type": "array", "items": {"type": "string"}}}},
        {"labels": "bug"},
    )
    coerce_arguments_by_schema(
        {"properties": {"enabled": {"type": "boolean"}}},
        {"enabled": 1},
    )
    stats = get_schema_coercion_stats()
    assert stats["scalar_to_array_wraps"] == 1
    assert stats["bool_number_cross_coercions"] == 1


# ---------------------------------------------------------------------------
# prepare_mcp_call_arguments tests (strict-host null stripping)
# ---------------------------------------------------------------------------


def test_prepare_mcp_call_arguments_strips_optional_nulls():
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "date": {"type": "string"},
            "trainFilterFlags": {"type": "string", "default": ""},
        },
        "required": ["date"],
    }
    prepared = prepare_mcp_call_arguments(
        {"date": "2026-08-06", "trainFilterFlags": None},
        schema,
    )
    assert prepared == {"date": "2026-08-06"}


def test_prepare_mcp_call_arguments_keeps_required_nullable_null():
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "payload": {"type": ["string", "null"]},
        },
        "required": ["payload"],
    }
    prepared = prepare_mcp_call_arguments({"payload": None}, schema)
    assert prepared == {"payload": None}

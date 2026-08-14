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
    schema = {
        "properties": {"dry_run": {"type": "boolean"}, "force": {"type": "boolean"}}
    }
    kwargs = {"dry_run": "true", "force": "False"}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["dry_run"] is True
    assert coerced["force"] is False


def test_coerce_arguments_number():
    schema = {
        "properties": {"limit": {"type": "integer"}, "threshold": {"type": "number"}}
    }
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
    """Decimal / exponent forms must still coerce to float for number schema."""
    schema = {"properties": {"a": {"type": "number"}, "b": {"type": "number"}}}
    coerced = coerce_arguments_by_schema(schema, {"a": "3.14", "b": "1e10"})
    assert coerced["a"] == 3.14
    assert isinstance(coerced["a"], float)
    assert coerced["b"] == 1e10
    assert isinstance(coerced["b"], float)


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
    schema = {
        "properties": {
            "items": {"type": ["array", "null"], "items": {"type": "string"}}
        }
    }
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

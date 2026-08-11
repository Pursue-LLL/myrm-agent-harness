import json

import myrm_agent_harness.toolkits.mcp.schema_utils as schema_utils_module
from myrm_agent_harness.toolkits.mcp.schema_utils import (
    analyze_schema_complexity,
    canonicalize_schema_for_cache,
    coerce_arguments_by_schema,
    coerce_value,
    collapse_const_unions,
    flatten_deep_schema,
    flatten_json_schema,
    flatten_top_level_composite,
    get_schema_coercion_stats,
    has_dot_keys,
    nest_flat_arguments,
    prepare_mcp_call_arguments,
    reset_schema_coercion_stats,
)

# ---------------------------------------------------------------------------
# Cache-stable canonicalization tests
# ---------------------------------------------------------------------------


def test_canonicalize_sorts_object_keys():
    """Object keys must be sorted for deterministic serialization."""
    schema = {
        "type": "object",
        "properties": {"b": {"type": "string"}, "a": {"type": "integer"}},
    }
    canonical = canonicalize_schema_for_cache(schema)
    assert list(canonical.keys()) == ["properties", "type"]
    assert list(canonical["properties"].keys()) == ["a", "b"]


def test_canonicalize_sorts_required_array():
    """``required`` is set-like and must be sorted."""
    schema = {"required": ["z", "a", "m"], "type": "object"}
    canonical = canonicalize_schema_for_cache(schema)
    assert canonical["required"] == ["a", "m", "z"]


def test_canonicalize_preserves_enum_order():
    """``enum`` values carry semantic ordering — must NOT be sorted."""
    schema = {
        "properties": {
            "mode": {"enum": ["fast", "balanced", "thorough"], "type": "string"}
        },
        "type": "object",
    }
    canonical = canonicalize_schema_for_cache(schema)
    assert canonical["properties"]["mode"]["enum"] == ["fast", "balanced", "thorough"]


def test_canonicalize_sorts_dependent_required():
    """``dependentRequired`` inner arrays are sorted; outer keys are sorted."""
    schema = {
        "dependentRequired": {"b": ["z", "a"], "a": ["y", "x"]},
        "type": "object",
    }
    canonical = canonicalize_schema_for_cache(schema)
    keys = list(canonical["dependentRequired"].keys())
    assert keys == ["a", "b"]
    assert canonical["dependentRequired"]["a"] == ["x", "y"]
    assert canonical["dependentRequired"]["b"] == ["a", "z"]


def test_canonicalize_dependent_required_non_scalar_items():
    """Non-scalar dependentRequired entries should recurse without crashing."""
    schema = {
        "dependentRequired": {
            "a": [{"field": "x"}, {"field": "a"}],
        }
    }
    canonical = canonicalize_schema_for_cache(schema)
    assert canonical["dependentRequired"]["a"][0] == {"field": "x"}


def test_canonicalize_idempotent():
    """Applying canonicalization twice yields the same result."""
    schema = {
        "required": ["c", "a"],
        "properties": {"c": {"type": "string"}, "a": {"type": "integer"}},
        "type": "object",
    }
    once = canonicalize_schema_for_cache(schema)
    twice = canonicalize_schema_for_cache(once)
    assert json.dumps(once, sort_keys=True) == json.dumps(twice, sort_keys=True)


def test_canonicalize_different_key_order_same_result():
    """Two schemas with identical content but different key orderings
    must produce identical JSON after canonicalization."""
    schema_a = {
        "type": "object",
        "properties": {"repo": {"type": "string"}},
        "required": ["repo"],
    }
    schema_b = {
        "required": ["repo"],
        "properties": {"repo": {"type": "string"}},
        "type": "object",
    }
    assert json.dumps(canonicalize_schema_for_cache(schema_a)) == json.dumps(
        canonicalize_schema_for_cache(schema_b)
    )


def test_canonicalize_scalars_passthrough():
    """Scalars and None pass through unchanged."""
    assert canonicalize_schema_for_cache(42) == 42
    assert canonicalize_schema_for_cache("hello") == "hello"
    assert canonicalize_schema_for_cache(None) is None
    assert canonicalize_schema_for_cache(True) is True


def test_canonicalize_empty_dict_and_list():
    """Empty containers must pass through without error."""
    assert canonicalize_schema_for_cache({}) == {}
    assert canonicalize_schema_for_cache([]) == []
    schema = {"properties": {}, "required": [], "type": "object"}
    canonical = canonicalize_schema_for_cache(schema)
    assert canonical == {"properties": {}, "required": [], "type": "object"}


def test_canonicalize_deep_nesting_recursive():
    """Keys at every nesting level must be sorted — 3+ depth."""
    schema = {
        "type": "object",
        "properties": {
            "z_outer": {
                "type": "object",
                "properties": {
                    "z_mid": {
                        "type": "object",
                        "properties": {
                            "z_inner": {"type": "string"},
                            "a_inner": {"type": "integer"},
                        },
                    },
                    "a_mid": {"type": "boolean"},
                },
            },
            "a_outer": {"type": "string"},
        },
    }
    canonical = canonicalize_schema_for_cache(schema)
    assert list(canonical["properties"].keys()) == ["a_outer", "z_outer"]
    z_outer = canonical["properties"]["z_outer"]
    assert list(z_outer["properties"].keys()) == ["a_mid", "z_mid"]
    z_mid = z_outer["properties"]["z_mid"]
    assert list(z_mid["properties"].keys()) == ["a_inner", "z_inner"]


def test_canonicalize_allof_anyof_arrays_preserved():
    """allOf/anyOf/oneOf arrays must NOT be sorted — they have semantic ordering."""
    schema = {
        "anyOf": [
            {"type": "string", "description": "text"},
            {"type": "integer", "description": "number"},
        ],
        "type": "object",
    }
    canonical = canonicalize_schema_for_cache(schema)
    assert canonical["anyOf"][0]["type"] == "string"
    assert canonical["anyOf"][1]["type"] == "integer"
    # But inner dict keys should still be sorted
    assert list(canonical["anyOf"][0].keys()) == ["description", "type"]


def test_canonicalize_items_nested_object():
    """Object schemas inside array items must also have sorted keys."""
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["name", "age"],
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
        },
    }
    canonical = canonicalize_schema_for_cache(schema)
    items = canonical["items"]
    assert list(items.keys()) == ["properties", "required", "type"]
    assert items["required"] == ["age", "name"]


def test_canonicalize_required_with_non_scalar_passthrough():
    """If required somehow contains non-scalar items, they should not crash."""
    schema = {"required": [{"complex": True}, "a_field"], "type": "object"}
    canonical = canonicalize_schema_for_cache(schema)
    assert canonical["required"][0] == {"complex": True}
    assert canonical["required"][1] == "a_field"


def test_canonicalize_mixed_real_world_schema():
    """Real-world-like schema with required, enum, properties, nested objects."""
    schema_v1 = {
        "type": "object",
        "required": ["repo", "branch"],
        "properties": {
            "repo": {"type": "string", "description": "Repository name"},
            "branch": {
                "type": "string",
                "enum": ["main", "develop", "staging"],
            },
            "options": {
                "type": "object",
                "properties": {
                    "force": {"type": "boolean"},
                    "depth": {"type": "integer"},
                },
                "required": ["force", "depth"],
            },
        },
    }
    schema_v2 = {
        "properties": {
            "options": {
                "required": ["depth", "force"],
                "type": "object",
                "properties": {
                    "depth": {"type": "integer"},
                    "force": {"type": "boolean"},
                },
            },
            "branch": {
                "enum": ["main", "develop", "staging"],
                "type": "string",
            },
            "repo": {"description": "Repository name", "type": "string"},
        },
        "required": ["branch", "repo"],
        "type": "object",
    }
    c1 = json.dumps(canonicalize_schema_for_cache(schema_v1))
    c2 = json.dumps(canonicalize_schema_for_cache(schema_v2))
    assert c1 == c2
    canonical = canonicalize_schema_for_cache(schema_v1)
    assert canonical["properties"]["branch"]["enum"] == ["main", "develop", "staging"]
    assert canonical["properties"]["options"]["required"] == ["depth", "force"]


# ---------------------------------------------------------------------------
# $ref flattening tests
# ---------------------------------------------------------------------------


def test_flatten_json_schema_basic():
    schema = {
        "properties": {"user": {"$ref": "#/definitions/User"}},
        "definitions": {
            "User": {"type": "object", "properties": {"name": {"type": "string"}}}
        },
    }

    flattened = flatten_json_schema(schema)
    assert "definitions" not in flattened
    assert flattened["properties"]["user"]["type"] == "object"
    assert flattened["properties"]["user"]["properties"]["name"]["type"] == "string"


def test_flatten_json_schema_infinite_recursion():
    # A schema that refers to itself to test the cycle breaker
    schema = {
        "properties": {"node": {"$ref": "#/definitions/Node"}},
        "definitions": {
            "Node": {
                "type": "object",
                "properties": {"child": {"$ref": "#/definitions/Node"}},
            }
        },
    }

    # Should not raise RecursionError
    flattened = flatten_json_schema(schema, max_depth=3)

    # Assert it stops at some point
    assert "definitions" not in flattened
    assert flattened["properties"]["node"]["type"] == "object"
    # The child might be truncated depending on max_depth,
    # the main goal is preventing RecursionError.
    assert "properties" in flattened["properties"]["node"]


def test_flatten_json_schema_non_dict_passthrough():
    payload = ["not", "a", "schema"]
    assert flatten_json_schema(payload) == payload


def test_flatten_json_schema_ref_merge_override_is_resolved():
    schema = {
        "type": "object",
        "properties": {
            "node": {
                "$ref": "#/definitions/Node",
                "description": {"$ref": "#/definitions/Label"},
            }
        },
        "definitions": {
            "Node": {"type": "object", "properties": {"id": {"type": "string"}}},
            "Label": {"type": "string"},
        },
    }
    flattened = flatten_json_schema(schema)
    assert flattened["properties"]["node"]["description"]["type"] == "string"
    assert flattened["properties"]["node"]["properties"]["id"]["type"] == "string"


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
    assert schema_utils_module._value_conforms_to_schema_types(schema, None) is True
    assert schema_utils_module._value_conforms_to_schema_types(schema, True) is True
    assert schema_utils_module._value_conforms_to_schema_types(schema, {"x": 1}) is True
    assert schema_utils_module._value_conforms_to_schema_types(schema, ["x"]) is True
    assert schema_utils_module._value_conforms_to_schema_types(schema, 1) is True
    assert schema_utils_module._value_conforms_to_schema_types(schema, 1.5) is True
    assert schema_utils_module._value_conforms_to_schema_types(schema, "x") is True


def test_coerce_value_non_dict_schema_passthrough():
    assert schema_utils_module.coerce_value("not-a-schema", "value") == "value"


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
# Deep-nesting flattening tests
# ---------------------------------------------------------------------------


def test_analyze_schema_complexity_flat():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
    }
    leaf_count, max_depth = analyze_schema_complexity(schema)
    assert leaf_count == 2
    assert max_depth == 1


def test_analyze_schema_complexity_deep():
    schema = {
        "type": "object",
        "properties": {
            "payment": {
                "type": "object",
                "properties": {
                    "card": {
                        "type": "object",
                        "properties": {
                            "number": {"type": "string"},
                            "cvc": {"type": "string"},
                        },
                    }
                },
            }
        },
    }
    leaf_count, max_depth = analyze_schema_complexity(schema)
    assert leaf_count == 2
    assert max_depth == 3


def test_analyze_schema_complexity_non_dict_zeroes():
    assert analyze_schema_complexity(["not", "schema"]) == (0, 0)


def test_flatten_deep_schema_below_threshold():
    """Schemas within threshold should not be flattened."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
    }
    result, meta = flatten_deep_schema(schema)
    assert meta.was_flattened is False
    assert result is schema


def test_flatten_deep_schema_non_dict_children_returns_original():
    schema = {
        "type": "object",
        "properties": {
            "broken": "non-dict-child",
        },
    }
    result, meta = flatten_deep_schema(schema, depth_threshold=0, leaf_threshold=0)
    assert result == schema
    assert meta.was_flattened is False


def test_flatten_deep_schema_stripe_like():
    """Stripe-like deep schema should be flattened to dot-paths."""
    schema = {
        "type": "object",
        "properties": {
            "amount": {"type": "integer", "description": "Amount in cents"},
            "currency": {"type": "string"},
            "payment_method": {
                "type": "object",
                "required": ["type", "card"],
                "properties": {
                    "type": {"type": "string", "enum": ["card"]},
                    "card": {
                        "type": "object",
                        "required": ["number", "exp_month", "exp_year", "cvc"],
                        "properties": {
                            "number": {"type": "string"},
                            "exp_month": {"type": "integer"},
                            "exp_year": {"type": "integer"},
                            "cvc": {"type": "string"},
                        },
                    },
                },
            },
        },
        "required": ["amount", "currency", "payment_method"],
    }
    result, meta = flatten_deep_schema(schema)
    assert meta.was_flattened is True
    props = result["properties"]
    assert "amount" in props
    assert "payment_method.type" in props
    assert "payment_method.card.number" in props
    assert "payment_method.card.exp_month" in props
    # Description preserved on leaf nodes
    assert props["amount"]["description"] == "Amount in cents"
    # Required fields flattened
    assert "amount" in result["required"]
    assert "payment_method.type" in result["required"]
    assert "payment_method.card.number" in result["required"]


def test_flatten_preserves_non_object_leaves():
    """Arrays and anyOf should be kept as leaf nodes, not expanded."""
    schema = {
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}},
            "config": {
                "type": "object",
                "properties": {
                    "mode": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                    "nested": {
                        "type": "object",
                        "properties": {
                            "deep1": {"type": "string"},
                            "deep2": {"type": "string"},
                            "deep3": {"type": "string"},
                            "deep4": {"type": "string"},
                            "deep5": {"type": "string"},
                            "deep6": {"type": "string"},
                            "deep7": {"type": "string"},
                            "deep8": {"type": "string"},
                            "deep9": {"type": "string"},
                        },
                    },
                },
            },
        },
    }
    result, meta = flatten_deep_schema(schema)
    assert meta.was_flattened is True
    props = result["properties"]
    # Array kept as leaf
    assert props["tags"]["type"] == "array"
    # anyOf kept as leaf
    assert "anyOf" in props["config.mode"]
    # Nested object properties flattened
    assert "config.nested.deep1" in props


def test_nest_flat_arguments():
    flat_args = {
        "amount": 1000,
        "payment_method.type": "card",
        "payment_method.card.number": "4242424242424242",
        "payment_method.card.exp_month": 12,
    }
    nested = nest_flat_arguments(flat_args)
    assert nested["amount"] == 1000
    assert nested["payment_method"]["type"] == "card"
    assert nested["payment_method"]["card"]["number"] == "4242424242424242"
    assert nested["payment_method"]["card"]["exp_month"] == 12


def test_nest_flat_arguments_passthrough():
    """Keys without dots should pass through unchanged."""
    args = {"name": "test", "count": 5}
    result = nest_flat_arguments(args)
    assert result == args


def test_has_dot_keys():
    assert has_dot_keys({"payment.card": "x"}) is True
    assert has_dot_keys({"name": "x", "age": 1}) is False
    assert has_dot_keys({}) is False


def test_flatten_and_nest_roundtrip():
    """Flatten + nest should preserve the original nested argument structure."""
    schema = {
        "type": "object",
        "properties": {
            "amount": {"type": "integer"},
            "meta": {
                "type": "object",
                "properties": {
                    "order": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "items": {"type": "integer"},
                        },
                    }
                },
            },
        },
    }
    # Force flatten by lowering threshold
    _result, meta = flatten_deep_schema(schema, depth_threshold=1, leaf_threshold=2)
    assert meta.was_flattened is True

    # Simulate model filling flat args
    flat_args = {"amount": 100, "meta.order.id": "ord_123", "meta.order.items": 3}
    nested = nest_flat_arguments(flat_args)
    assert nested == {"amount": 100, "meta": {"order": {"id": "ord_123", "items": 3}}}


# ---------------------------------------------------------------------------
# Edge-case coverage for uncovered branches
# ---------------------------------------------------------------------------


def test_flatten_json_schema_list_in_definitions():
    """$ref resolution handles list nodes within schemas (L149)."""
    schema = {
        "type": "object",
        "properties": {
            "tags": {
                "$ref": "#/definitions/TagList",
            }
        },
        "definitions": {
            "TagList": {
                "type": "array",
                "items": {"type": "string"},
                "examples": ["alpha", "beta"],
            }
        },
    }
    result = flatten_json_schema(schema)
    assert result["properties"]["tags"]["type"] == "array"
    assert result["properties"]["tags"]["examples"] == ["alpha", "beta"]
    assert "definitions" not in result


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


def test_flatten_deep_schema_non_dict_child():
    """flatten_deep_schema skips non-dict children in properties (L498)."""
    schema = {
        "type": "object",
        "properties": {
            "valid": {"type": "string"},
            "invalid_child": "not_a_dict",
            "nested": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                    "c": {"type": "integer"},
                },
            },
        },
    }
    result, meta = flatten_deep_schema(schema, depth_threshold=0, leaf_threshold=0)
    assert meta.was_flattened is True
    assert "valid" in result["properties"]
    assert "nested.a" in result["properties"]
    assert "invalid_child" not in result["properties"]


def test_flatten_deep_schema_empty_result():
    """flatten_deep_schema returns original when _collect yields nothing (L512)."""
    schema = {
        "type": "object",
        "properties": {},
    }
    result, meta = flatten_deep_schema(schema, depth_threshold=0, leaf_threshold=0)
    assert meta.was_flattened is False
    assert result == schema


def test_coerce_value_null_only_schema_string_passthrough():
    """coerce_value with type:null schema leaves non-null string unchanged (L240)."""
    schema = {"type": "null"}
    result = coerce_value(schema, "some_string")
    assert result == "some_string"


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


# ---------------------------------------------------------------------------
# Top-level composite flattening tests
# ---------------------------------------------------------------------------


def test_flatten_top_level_composite_oneof_kimi_cu_style():
    """kimi-cu click-style oneOf: index *or* x/y must survive flattening."""
    schema = {
        "type": "object",
        "oneOf": [
            {"type": "object", "properties": {"index": {"type": "integer"}}},
            {
                "type": "object",
                "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
            },
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["type"] == "object"
    assert set(result["properties"]) == {"index", "x", "y"}
    assert "oneOf" not in result
    assert "required" not in result
    assert "mutually exclusive" in result["description"]
    assert "(index)" in result["description"]
    assert "(x, y)" in result["description"]


def test_flatten_top_level_composite_allof_merges_required():
    """allOf branches are conjunctive — properties and required merge."""
    schema = {
        "allOf": [
            {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            {
                "type": "object",
                "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
                "required": ["tags"],
            },
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["type"] == "object"
    assert set(result["properties"]) == {"id", "tags"}
    assert set(result["required"]) == {"id", "tags"}
    assert "allOf" not in result


def test_flatten_top_level_composite_single_branch_no_constraint():
    """A single object branch needs no mutual-exclusivity hint."""
    schema = {
        "anyOf": [
            {"type": "object", "properties": {"query": {"type": "string"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["properties"] == {"query": {"type": "string"}}
    assert "description" not in result


def test_flatten_top_level_composite_idempotent_no_composite():
    """Schemas without top-level composite pass through unchanged (same object)."""
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    assert flatten_top_level_composite(schema) is schema


def test_flatten_top_level_composite_preserves_metadata():
    """description/title/default on the wrapper are preserved."""
    schema = {
        "description": "Activate a window",
        "oneOf": [
            {"type": "object", "properties": {"windowId": {"type": "string"}}},
            {"type": "object", "properties": {"name": {"type": "string"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert "Activate a window" in result["description"]
    assert "mutually exclusive" in result["description"]
    assert set(result["properties"]) == {"windowId", "name"}


def test_flatten_top_level_composite_skips_non_object_branches():
    """Non-object branches (null/string) are ignored during merging."""
    schema = {
        "anyOf": [
            {"type": "object", "properties": {"a": {"type": "string"}}},
            {"type": "null"},
            {"type": "string"},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["properties"] == {"a": {"type": "string"}}
    assert "description" not in result


def test_flatten_top_level_composite_keeps_top_level_properties():
    """Top-level properties coexist conjunctively with the composite keyword."""
    schema = {
        "type": "object",
        "properties": {"windowId": {"type": "string"}},
        "required": ["windowId"],
        "oneOf": [
            {"type": "object", "properties": {"index": {"type": "integer"}}},
            {"type": "object", "properties": {"x": {"type": "number"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert set(result["properties"]) == {"windowId", "index", "x"}
    assert result["required"] == ["windowId"]
    # Top-level property is conjunctive — never part of the exclusive groups.
    assert "windowId" not in result["description"]


def test_flatten_top_level_composite_keeps_top_level_required_with_allof():
    """Top-level required merges conjunctively with allOf branch required."""
    schema = {
        "type": "object",
        "required": ["tenant"],
        "allOf": [
            {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            {"type": "object", "properties": {"tags": {"type": "array"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert set(result["required"]) == {"tenant", "id"}


def test_flatten_top_level_composite_branch_without_type():
    """A branch with properties but no type keyword must still merge."""
    schema = {
        "oneOf": [
            {"properties": {"index": {"type": "integer"}}},
            {"type": "object", "properties": {"x": {"type": "number"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert set(result["properties"]) == {"index", "x"}
    assert "mutually exclusive" in result["description"]


def test_flatten_top_level_composite_oneof_const_union_preserves_discriminator():
    """Discriminator const values must union across oneOf branches (not overwrite)."""
    schema = {
        "type": "object",
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "action": {"const": "click", "description": "动作类型"},
                    "index": {"type": "integer"},
                },
                "required": ["action", "index"],
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "type", "description": "动作类型"},
                    "text": {"type": "string"},
                },
                "required": ["action", "text"],
            },
        ],
    }
    result = flatten_top_level_composite(schema)
    action = result["properties"]["action"]
    assert action["enum"] == ["click", "type"]
    assert action["description"] == "动作类型"
    # Required by every branch → promoted; the discriminator is not an option.
    assert result["required"] == ["action"]
    assert "action" not in result["description"]
    assert "(index)" in result["description"]
    assert "(text)" in result["description"]


def test_flatten_top_level_composite_oneof_enum_union_across_branches():
    """Same-name enum properties across anyOf branches union without losing values."""
    schema = {
        "anyOf": [
            {"type": "object", "properties": {"sort": {"enum": ["asc", "desc"]}}},
            {"type": "object", "properties": {"sort": {"enum": ["recent"]}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["properties"]["sort"]["enum"] == ["asc", "desc", "recent"]


def test_flatten_top_level_composite_union_merges_different_descriptions():
    """Different descriptions on the merged discriminator are both kept."""
    schema = {
        "anyOf": [
            {
                "type": "object",
                "properties": {"m": {"const": "a", "description": "desc A"}},
            },
            {
                "type": "object",
                "properties": {"m": {"const": "b", "description": "desc B"}},
            },
        ],
    }
    result = flatten_top_level_composite(schema)
    merged = result["properties"]["m"]
    assert merged["enum"] == ["a", "b"]
    assert merged["description"] == "desc A desc B"


def test_flatten_top_level_composite_conflicting_types_keep_first_definition():
    """Non-enumerable same-name properties keep the first branch's definition."""
    schema = {
        "anyOf": [
            {
                "type": "object",
                "properties": {
                    "opts": {"type": "array", "items": {"type": "string"}}
                },
            },
            {"type": "object", "properties": {"opts": {"type": "string"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["properties"]["opts"] == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_flatten_top_level_composite_common_required_promotion_is_all_branches():
    """Only properties required by every branch are promoted to top-level required."""
    schema = {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "a": {"type": "string"},
                    "b": {"type": "string"},
                },
                "required": ["a", "b"],
            },
            {
                "type": "object",
                "properties": {
                    "a": {"type": "string"},
                    "c": {"type": "string"},
                },
                "required": ["a"],
            },
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["required"] == ["a"]


def test_flatten_top_level_composite_single_branch_required_not_promoted():
    """A lone alternative branch keeps its previous behavior (no promotion)."""
    schema = {
        "anyOf": [
            {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ],
    }
    result = flatten_top_level_composite(schema)
    assert "required" not in result


def test_flatten_top_level_composite_const_union_deduplicates_shared_values():
    """Duplicate values across branches collapse into a single enum entry."""
    schema = {
        "anyOf": [
            {
                "type": "object",
                "properties": {"mode": {"enum": ["auto", "manual"]}},
            },
            {
                "type": "object",
                "properties": {"mode": {"const": "auto"}},
            },
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["properties"]["mode"]["enum"] == ["auto", "manual"]


def test_flatten_top_level_composite_malformed_non_dict_property_survives():
    """A non-dict property value in one branch must not crash the merge."""
    schema = {
        "anyOf": [
            {
                "type": "object",
                "properties": {"mode": {"const": "fast"}, "note": "legacy-string"},
            },
            {"type": "object", "properties": {"mode": {"const": "slow"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["properties"]["mode"]["enum"] == ["fast", "slow"]
    assert result["properties"]["note"] == "legacy-string"


def test_flatten_top_level_composite_union_keeps_title():
    """A shared title on the merged discriminator property is preserved."""
    schema = {
        "anyOf": [
            {
                "type": "object",
                "properties": {
                    "action": {"const": "up", "title": "操作"},
                },
            },
            {"type": "object", "properties": {"action": {"const": "down"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["properties"]["action"]["title"] == "操作"
    assert result["properties"]["action"]["enum"] == ["up", "down"]


def test_collapse_const_unions_string_enum():
    """String const unions collapse into a typed enum."""
    schema = {
        "type": "object",
        "properties": {"color": {"anyOf": [{"const": "red"}, {"const": "green"}]}},
    }
    result = collapse_const_unions(schema)
    assert result["properties"]["color"] == {
        "type": "string",
        "enum": ["red", "green"],
    }


def test_collapse_const_unions_integer_enum():
    """Integer const unions collapse preserving the numeric type."""
    result = collapse_const_unions({"anyOf": [{"const": 1}, {"const": 2}]})
    assert result == {"type": "integer", "enum": [1, 2]}


def test_collapse_const_unions_bool_not_merged_into_integer():
    """True/False are booleans and never merge with integer consts."""
    schema = {"anyOf": [{"const": True}, {"const": 1}]}
    assert collapse_const_unions(schema) == schema


def test_collapse_const_unions_mixed_types_passthrough():
    """Mixed-typed const unions are left untouched."""
    schema = {"anyOf": [{"const": "red"}, {"const": 1}]}
    assert collapse_const_unions(schema) == schema


def test_collapse_const_unions_constrained_branch_rejected():
    """A const branch carrying extra constraining keywords is not pure."""
    schema = {"anyOf": [{"const": "red", "minLength": 2}, {"const": "green"}]}
    assert collapse_const_unions(schema) == schema


def test_collapse_const_unions_declared_type_mismatch_rejected():
    """A const whose declared type disagrees with its value blocks the fold."""
    schema = {"anyOf": [{"const": "red", "type": "integer"}, {"const": "green"}]}
    assert collapse_const_unions(schema) == schema


def test_collapse_const_unions_null_branch_becomes_nullable():
    """A lone null branch is dropped and recorded as nullable."""
    result = collapse_const_unions({"anyOf": [{"const": "red"}, {"type": "null"}]})
    assert result == {"type": "string", "enum": ["red"], "nullable": True}


def test_collapse_const_unions_recursive_nested_properties():
    """Const unions nested deep inside properties are folded recursively."""
    schema = {
        "type": "object",
        "properties": {
            "inner": {
                "type": "object",
                "properties": {"mode": {"anyOf": [{"const": "a"}, {"const": "b"}]}},
            }
        },
    }
    result = collapse_const_unions(schema)
    assert result["properties"]["inner"]["properties"]["mode"] == {
        "type": "string",
        "enum": ["a", "b"],
    }


def test_collapse_const_unions_keeps_outer_metadata():
    """Outer title/description/default are carried onto the replacement."""
    schema = {
        "description": "pick one color",
        "default": "red",
        "anyOf": [{"const": "red"}, {"const": "green"}],
    }
    result = collapse_const_unions(schema)
    assert result["description"] == "pick one color"
    assert result["default"] == "red"
    assert result["enum"] == ["red", "green"]


def test_collapse_const_unions_idempotent():
    """Collapsing an already-folded enum is a no-op."""
    schema = {
        "type": "object",
        "properties": {"color": {"anyOf": [{"const": "red"}, {"const": "green"}]}},
    }
    once = collapse_const_unions(schema)
    assert collapse_const_unions(once) == once


def test_collapse_const_unions_chain_with_flatten():
    """Property-level const union + top-level discriminator flatten coexist."""
    schema = {
        "type": "object",
        "properties": {"color": {"anyOf": [{"const": "red"}, {"const": "green"}]}},
        "oneOf": [
            {
                "type": "object",
                "properties": {"action": {"const": "click"}, "idx": {"type": "integer"}},
                "required": ["action"],
            },
            {
                "type": "object",
                "properties": {"action": {"const": "type"}, "txt": {"type": "string"}},
                "required": ["action"],
            },
        ],
    }
    collapsed = collapse_const_unions(flatten_json_schema(schema))
    result = flatten_top_level_composite(collapsed)
    assert result["properties"]["color"]["enum"] == ["red", "green"]
    assert result["properties"]["action"]["enum"] == ["click", "type"]
    assert result["required"] == ["action"]

import json

from myrm_agent_harness.toolkits.mcp.schema_utils import (
    analyze_schema_complexity,
    canonicalize_schema_for_cache,
    coerce_arguments_by_schema,
    flatten_deep_schema,
    flatten_json_schema,
    has_dot_keys,
    nest_flat_arguments,
)

# ---------------------------------------------------------------------------
# Cache-stable canonicalization tests
# ---------------------------------------------------------------------------


def test_canonicalize_sorts_object_keys():
    """Object keys must be sorted for deterministic serialization."""
    schema = {"type": "object", "properties": {"b": {"type": "string"}, "a": {"type": "integer"}}}
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
        "properties": {"mode": {"enum": ["fast", "balanced", "thorough"], "type": "string"}},
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


def test_canonicalize_idempotent():
    """Applying canonicalization twice yields the same result."""
    schema = {"required": ["c", "a"], "properties": {"c": {"type": "string"}, "a": {"type": "integer"}}, "type": "object"}
    once = canonicalize_schema_for_cache(schema)
    twice = canonicalize_schema_for_cache(once)
    assert json.dumps(once, sort_keys=True) == json.dumps(twice, sort_keys=True)


def test_canonicalize_different_key_order_same_result():
    """Two schemas with identical content but different key orderings
    must produce identical JSON after canonicalization."""
    schema_a = {"type": "object", "properties": {"repo": {"type": "string"}}, "required": ["repo"]}
    schema_b = {"required": ["repo"], "properties": {"repo": {"type": "string"}}, "type": "object"}
    assert json.dumps(canonicalize_schema_for_cache(schema_a)) == json.dumps(canonicalize_schema_for_cache(schema_b))


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
        "definitions": {"User": {"type": "object", "properties": {"name": {"type": "string"}}}},
    }

    flattened = flatten_json_schema(schema)
    assert "definitions" not in flattened
    assert flattened["properties"]["user"]["type"] == "object"
    assert flattened["properties"]["user"]["properties"]["name"]["type"] == "string"


def test_flatten_json_schema_infinite_recursion():
    # A schema that refers to itself to test the cycle breaker
    schema = {
        "properties": {"node": {"$ref": "#/definitions/Node"}},
        "definitions": {"Node": {"type": "object", "properties": {"child": {"$ref": "#/definitions/Node"}}}},
    }

    # Should not raise RecursionError
    flattened = flatten_json_schema(schema, max_depth=3)

    # Assert it stops at some point
    assert "definitions" not in flattened
    assert flattened["properties"]["node"]["type"] == "object"
    # The child might be truncated depending on max_depth,
    # the main goal is preventing RecursionError.
    assert "properties" in flattened["properties"]["node"]


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


def test_coerce_arguments_recursive():
    schema = {
        "properties": {
            "filters": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}, "tags": {"type": "array", "items": {"type": "boolean"}}},
            }
        }
    }
    # LLM hallucinates stringified integer and boolean inside a nested object
    kwargs = {"filters": {"limit": "42", "tags": ["true", "False"]}}
    coerced = coerce_arguments_by_schema(schema, kwargs)
    assert coerced["filters"]["limit"] == 42
    assert coerced["filters"]["tags"] == [True, False]


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

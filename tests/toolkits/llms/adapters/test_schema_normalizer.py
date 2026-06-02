"""Tests for tool schema normalization.

Covers: nullable anyOf, oneOf, allOf, $ref/$defs, top-level composite,
nested objects/arrays, passthrough of already-valid schemas, and edge cases.
"""

from myrm_agent_harness.toolkits.llms.adapters.schema_normalizer import (
    normalize_tool_schema,
)


def _wrap(params: dict) -> dict:
    """Wrap a parameters dict into OpenAI tool format."""
    return {"type": "function", "function": {"name": "t", "description": "d", "parameters": params}}


def _params(tool: dict) -> dict:
    return tool["function"]["parameters"]


class TestNullableAnyOf:
    """anyOf with null branch (most common MCP pattern)."""

    def test_nullable_integer(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Max results",
                        "default": None,
                    }
                },
                "required": ["limit"],
            }
        )
        result = _params(normalize_tool_schema(schema))

        assert result["properties"]["limit"]["type"] == "integer"
        assert result["properties"]["limit"]["description"] == "Max results"
        assert result["properties"]["limit"]["default"] is None
        assert "anyOf" not in result["properties"]["limit"]

    def test_nullable_string(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"name": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["name"]["type"] == "string"
        assert "anyOf" not in result["properties"]["name"]

    def test_nullable_object(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "config": {
                        "anyOf": [
                            {"type": "object", "properties": {"key": {"type": "string"}}},
                            {"type": "null"},
                        ]
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["config"]["type"] == "object"
        assert "key" in result["properties"]["config"]["properties"]
        assert "anyOf" not in result["properties"]["config"]


class TestOneOf:
    """oneOf with multiple type branches."""

    def test_oneof_with_null(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "value": {
                        "oneOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Optional value",
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["value"]["type"] == "string"
        assert result["properties"]["value"]["description"] == "Optional value"

    def test_oneof_multi_types_picks_first_non_null(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "data": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "integer"},
                            {"type": "null"},
                        ]
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["data"]["type"] == "string"


class TestAllOf:
    """allOf normalization."""

    def test_allof_single_branch(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "item": {
                        "allOf": [{"type": "object", "properties": {"id": {"type": "string"}}}],
                        "description": "An item",
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["item"]["type"] == "object"
        assert result["properties"]["item"]["description"] == "An item"

    def test_allof_multi_branch_merges_properties(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "user": {
                        "allOf": [
                            {
                                "type": "object",
                                "properties": {"name": {"type": "string"}, "email": {"type": "string"}},
                                "required": ["name", "email"],
                            },
                            {
                                "type": "object",
                                "properties": {"age": {"type": "integer"}, "role": {"type": "string"}},
                            },
                        ],
                        "description": "User data",
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        user = result["properties"]["user"]
        assert user["type"] == "object"
        assert "name" in user["properties"]
        assert "email" in user["properties"]
        assert "age" in user["properties"]
        assert "role" in user["properties"]
        assert user["required"] == ["name", "email"]
        assert user["description"] == "User data"
        assert "allOf" not in user

    def test_allof_multi_branch_dedup_required(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "item": {
                        "allOf": [
                            {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
                            {"type": "object", "properties": {"b": {"type": "string"}}, "required": ["a", "b"]},
                        ]
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["item"]["required"] == ["a", "b"]

    def test_allof_mixed_types_falls_back(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "data": {
                        "allOf": [
                            {"type": "object", "properties": {"a": {"type": "string"}}},
                            {"type": "string"},
                        ]
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["data"]["type"] == "object"


class TestRefResolution:
    """$ref and $defs inline resolution."""

    def test_defs_resolution(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"user": {"$ref": "#/$defs/User"}},
                "$defs": {
                    "User": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "age": {"type": "integer"},
                        },
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert "$ref" not in result["properties"]["user"]
        assert result["properties"]["user"]["type"] == "object"
        assert "name" in result["properties"]["user"]["properties"]
        assert "$defs" not in result

    def test_definitions_resolution(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"item": {"$ref": "#/definitions/Item"}},
                "definitions": {"Item": {"type": "string", "description": "An item ID"}},
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["item"]["type"] == "string"
        assert "definitions" not in result

    def test_nullable_ref(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "config": {
                        "anyOf": [
                            {"$ref": "#/$defs/Config"},
                            {"type": "null"},
                        ]
                    }
                },
                "$defs": {
                    "Config": {
                        "type": "object",
                        "properties": {"key": {"type": "string"}},
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        prop = result["properties"]["config"]
        assert prop["type"] == "object"
        assert "key" in prop["properties"]
        assert "anyOf" not in prop


class TestTopLevelComposite:
    """Top-level anyOf/oneOf in parameters."""

    def test_top_level_anyof_single_object(self) -> None:
        schema = _wrap(
            {
                "anyOf": [
                    {"type": "object", "properties": {"a": {"type": "string"}}},
                    {"type": "null"},
                ]
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["type"] == "object"
        assert "a" in result["properties"]

    def test_top_level_missing_type_with_properties(self) -> None:
        schema = _wrap(
            {
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["type"] == "object"
        assert "query" in result["properties"]


class TestNestedSchemas:
    """Nested objects and arrays."""

    def test_nested_object_nullable(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "outer": {
                        "type": "object",
                        "properties": {"inner": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        inner = result["properties"]["outer"]["properties"]["inner"]
        assert inner["type"] == "string"
        assert "anyOf" not in inner

    def test_array_items_nullable(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        items_schema = result["properties"]["items"]["items"]
        assert items_schema["type"] == "string"
        assert "anyOf" not in items_schema


class TestPassthrough:
    """Already-valid schemas should pass through unchanged."""

    def test_simple_schema_unchanged(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "count": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result == schema["function"]["parameters"]

    def test_no_parameters(self) -> None:
        tool = {"type": "function", "function": {"name": "t", "description": "d"}}
        result = normalize_tool_schema(tool)
        assert result == tool

    def test_non_function_tool(self) -> None:
        tool = {"type": "web_search_preview"}
        result = normalize_tool_schema(tool)
        assert result == tool


class TestEdgeCases:
    """Edge cases and robustness."""

    def test_empty_properties(self) -> None:
        schema = _wrap({"type": "object", "properties": {}})
        result = _params(normalize_tool_schema(schema))
        assert result["type"] == "object"
        assert result["properties"] == {}

    def test_does_not_mutate_original(self) -> None:
        original = _wrap(
            {
                "type": "object",
                "properties": {"x": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
            }
        )
        import copy

        frozen = copy.deepcopy(original)
        normalize_tool_schema(original)
        assert original == frozen

    def test_preserves_required_field(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "a": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["required"] == ["a", "b"]

    def test_preserves_title_and_examples(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "mode": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "title": "Operation Mode",
                        "examples": ["fast", "slow"],
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["mode"]["title"] == "Operation Mode"
        assert result["properties"]["mode"]["examples"] == ["fast", "slow"]

    def test_deeply_nested_refs(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "object",
                        "properties": {"child": {"$ref": "#/$defs/Child"}},
                    }
                },
                "$defs": {
                    "Child": {
                        "type": "object",
                        "properties": {"value": {"anyOf": [{"type": "number"}, {"type": "null"}]}},
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        child = result["properties"]["root"]["properties"]["child"]
        assert child["type"] == "object"
        assert child["properties"]["value"]["type"] == "number"
        assert "anyOf" not in child["properties"]["value"]


class TestStrictProviderCompat:
    """Tests for strict provider compatibility (Moonshot/Kimi)."""

    def test_missing_type_inferred_as_string(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"query": {"description": "Search term"}},
                "required": ["query"],
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["query"]["type"] == "string"
        assert result["properties"]["query"]["description"] == "Search term"

    def test_missing_type_inferred_as_object(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "config": {"properties": {"key": {"type": "string"}}}
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["config"]["type"] == "object"

    def test_missing_type_inferred_as_array(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"tags": {"items": {"type": "string"}}},
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["tags"]["type"] == "array"

    def test_missing_type_inferred_from_enum(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"mode": {"enum": ["fast", "slow"]}},
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["mode"]["type"] == "string"

    def test_missing_type_inferred_from_integer_enum(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"count": {"enum": [1, 5, 10]}},
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["count"]["type"] == "integer"

    def test_enum_null_cleanup(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "sort": {"type": "string", "enum": ["asc", "desc", None, ""]},
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["sort"]["enum"] == ["asc", "desc"]

    def test_enum_all_null_removed(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"val": {"type": "string", "enum": [None, ""]}},
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert "enum" not in result["properties"]["val"]

    def test_enum_on_object_type_not_cleaned(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "data": {"type": "object", "enum": [None, {"key": "val"}]},
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["data"]["enum"] == [None, {"key": "val"}]

    def test_tuple_items_collapsed(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "coords": {
                        "type": "array",
                        "items": [{"type": "number"}, {"type": "number"}],
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        items = result["properties"]["coords"]["items"]
        assert isinstance(items, dict)
        assert items["type"] == "number"

    def test_empty_tuple_items(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"data": {"type": "array", "items": []}},
            }
        )
        result = _params(normalize_tool_schema(schema))
        items = result["properties"]["data"]["items"]
        assert isinstance(items, dict)
        assert items.get("type") == "string"

    def test_nullable_keyword_removed(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"name": {"type": "string", "nullable": True}},
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert "nullable" not in result["properties"]["name"]
        assert result["properties"]["name"]["type"] == "string"

    def test_nullable_removed_preserves_other_fields(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "nullable": True,
                        "description": "Optional title",
                        "default": None,
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        prop = result["properties"]["title"]
        assert "nullable" not in prop
        assert prop["description"] == "Optional title"
        assert prop["default"] is None

    def test_existing_type_not_overwritten(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"count": {"type": "integer", "description": "N"}},
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["count"]["type"] == "integer"

    def test_combined_nullable_and_missing_type(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "filter": {"nullable": True, "description": "Optional filter"}
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        prop = result["properties"]["filter"]
        assert "nullable" not in prop
        assert prop["type"] == "string"
        assert prop["description"] == "Optional filter"

    def test_anyof_branch_enum_cleaned(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "sort": {
                        "anyOf": [
                            {"type": "string", "enum": ["asc", "desc", None, ""]},
                            {"type": "null"},
                        ]
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        prop = result["properties"]["sort"]
        assert prop["type"] == "string"
        assert prop["enum"] == ["asc", "desc"]
        assert "anyOf" not in prop

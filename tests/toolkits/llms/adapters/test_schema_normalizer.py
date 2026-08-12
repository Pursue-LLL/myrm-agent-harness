"""Tests for tool schema normalization.

Covers: nullable anyOf, oneOf, allOf, $ref/$defs, top-level composite,
nested objects/arrays, passthrough of already-valid schemas, edge cases,
and Anthropic-specific unsupported keyword stripping.
"""

from myrm_agent_harness.toolkits.llms.adapters.schema import normalize_tool_schema


def _wrap(params: dict) -> dict:
    """Wrap a parameters dict into OpenAI tool format."""
    return {
        "type": "function",
        "function": {"name": "t", "description": "d", "parameters": params},
    }


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
                "properties": {
                    "name": {"anyOf": [{"type": "string"}, {"type": "null"}]}
                },
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
                            {
                                "type": "object",
                                "properties": {"key": {"type": "string"}},
                            },
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

    def test_oneof_multiple_object_branches_merged(self) -> None:
        """Nested union of objects keeps every branch's parameters visible."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "oneOf": [
                            {
                                "type": "object",
                                "properties": {"url": {"type": "string"}},
                                "required": ["url"],
                            },
                            {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                                "required": ["path"],
                            },
                        ],
                        "description": "pick a target",
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        target = result["properties"]["target"]
        assert target["type"] == "object"
        assert "url" in target["properties"]
        assert "path" in target["properties"]
        assert "oneOf" not in target
        assert target["description"].startswith("pick a target")
        assert "(url)" in target["description"]
        assert "(path)" in target["description"]

    def test_anyof_object_branches_merge_discriminator_const_union(self) -> None:
        """Discriminator const values survive across anyOf object branches."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "filter": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "op": {"const": "eq"},
                                    "field": {"type": "string"},
                                },
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "op": {"const": "range"},
                                    "min": {"type": "number"},
                                    "max": {"type": "number"},
                                },
                            },
                        ],
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        filter_prop = result["properties"]["filter"]
        assert filter_prop["type"] == "object"
        assert set(filter_prop["properties"]["op"]["enum"]) == {"eq", "range"}
        assert "field" in filter_prop["properties"]
        assert "min" in filter_prop["properties"]
        assert "max" in filter_prop["properties"]
        assert "anyOf" not in filter_prop

    def test_anyof_branch_metadata_merged_into_union(self) -> None:
        """Branch-level descriptions survive discriminator union merging."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "filter": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "op": {
                                        "const": "eq",
                                        "description": "Equality match",
                                        "title": "Equal",
                                    }
                                },
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "op": {
                                        "const": "range",
                                        "description": "Range match",
                                        "title": "Range",
                                    }
                                },
                            },
                        ],
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        op = result["properties"]["filter"]["properties"]["op"]
        assert set(op["enum"]) == {"eq", "range"}
        assert op["description"] == "Equality match Range match"
        assert op["title"] == "Equal"

    def test_anyof_branch_metadata_deduped_when_equal(self) -> None:
        """Identical descriptions dedupe instead of concatenating."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "filter": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "op": {"const": "eq", "description": "Match op"}
                                },
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "op": {
                                        "const": "range",
                                        "description": "Match op",
                                    }
                                },
                            },
                        ],
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        op = result["properties"]["filter"]["properties"]["op"]
        assert op["description"] == "Match op"

    def test_anyof_closed_plus_open_keeps_closed_metadata(self) -> None:
        """A closed const unioned with an open type keeps closed-side metadata."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "config": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "mode": {
                                        "const": "auto",
                                        "description": "Automatic",
                                    }
                                },
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "mode": {"type": "string"},
                                },
                            },
                        ],
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        config = result["properties"]["config"]
        mode = config["properties"]["mode"]
        assert mode["type"] == "string"
        assert "const" not in mode
        assert "enum" not in mode
        assert mode["description"] == "Automatic"

    def test_anyof_branch_default_merged_first_wins(self) -> None:
        """Union merging keeps the first branch's default, not the second's."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "filter": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "op": {
                                        "const": "eq",
                                        "description": "Equality match",
                                        "default": "eq",
                                    }
                                },
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "op": {
                                        "const": "range",
                                        "description": "Range match",
                                        "default": "range",
                                    }
                                },
                            },
                        ],
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        op = result["properties"]["filter"]["properties"]["op"]
        assert set(op["enum"]) == {"eq", "range"}
        assert op["description"] == "Equality match Range match"
        assert op["default"] == "eq"

    def test_anyof_branch_metadata_single_side_kept(self) -> None:
        """A description present on only one branch survives union merging."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "filter": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "op": {
                                        "const": "eq",
                                        "description": "Equality match",
                                    }
                                },
                            },
                            {
                                "type": "object",
                                "properties": {"op": {"const": "range"}},
                            },
                        ],
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        op = result["properties"]["filter"]["properties"]["op"]
        assert set(op["enum"]) == {"eq", "range"}
        assert op["description"] == "Equality match"

    def test_allof_closed_plus_open_merges_both_metadata(self) -> None:
        """Intersecting a closed enum with an open type keeps both descriptions."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "item": {
                        "allOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "color": {
                                        "type": "string",
                                        "enum": ["red", "green"],
                                        "description": "Primary colors",
                                    }
                                },
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "color": {
                                        "type": "string",
                                        "description": "Any allowed color",
                                    }
                                },
                            },
                        ]
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        color = result["properties"]["item"]["properties"]["color"]
        assert color["enum"] == ["red", "green"]
        assert color["description"] == "Primary colors Any allowed color"

    def test_union_keeps_shared_type_across_consts(self) -> None:
        """Union merging carries a shared explicit type onto the merged enum."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "filter": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "op": {"type": "string", "const": "eq"}
                                },
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "op": {"type": "string", "const": "range"}
                                },
                            },
                        ],
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        op = result["properties"]["filter"]["properties"]["op"]
        assert op["type"] == "string"
        assert set(op["enum"]) == {"eq", "range"}

    def test_union_open_redefinition_keeps_first(self) -> None:
        """Redefining an unconstrained property across branches keeps the first."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "filter": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "op": {"type": "string", "description": "First"}
                                },
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "op": {"type": "string", "description": "Second"}
                                },
                            },
                        ],
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        op = result["properties"]["filter"]["properties"]["op"]
        assert op["type"] == "string"
        assert op["description"] == "First"

    def test_intersect_empty_keeps_first(self) -> None:
        """A disjoint allOf enum intersection keeps the first definition."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "item": {
                        "allOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "color": {
                                        "type": "string",
                                        "enum": ["red"],
                                        "description": "Red only",
                                    }
                                },
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "color": {
                                        "type": "string",
                                        "enum": ["blue"],
                                        "description": "Blue only",
                                    }
                                },
                            },
                        ]
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        color = result["properties"]["item"]["properties"]["color"]
        assert color["enum"] == ["red"]
        assert color["description"] == "Red only"

    def test_intersect_open_redefinition_keeps_first(self) -> None:
        """Redefining an unconstrained allOf property keeps the first."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "item": {
                        "allOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "First name",
                                    }
                                },
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "Second name",
                                    }
                                },
                            },
                        ]
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        name = result["properties"]["item"]["properties"]["name"]
        assert name["type"] == "string"
        assert name["description"] == "First name"

    def test_union_mixed_branch_types_skip_non_object(self) -> None:
        """Non-object branches are ignored when merging object alternatives."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "oneOf": [
                            {
                                "type": "object",
                                "properties": {"url": {"type": "string"}},
                            },
                            {"type": "string"},
                            {"type": "integer"},
                        ],
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        target = result["properties"]["target"]
        assert target["type"] == "object"
        assert "url" in target["properties"]
        assert "oneOf" not in target

    def test_union_empty_object_branches_fallback(self) -> None:
        """Object branches without properties produce a permissive schema."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "oneOf": [{"type": "object"}, {"type": "object"}],
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        target = result["properties"]["target"]
        assert target["type"] == "object"
        assert target["additionalProperties"] is True

    def test_allof_branch_metadata_merged_into_intersection(self) -> None:
        """Intersecting allOf branches keep descriptions from both sides."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "item": {
                        "allOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "color": {
                                        "type": "string",
                                        "enum": ["red", "green"],
                                        "description": "Primary colors",
                                    }
                                },
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "color": {
                                        "type": "string",
                                        "enum": ["green", "blue"],
                                        "description": "Cool colors",
                                    }
                                },
                            },
                        ]
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        color = result["properties"]["item"]["properties"]["color"]
        assert color["enum"] == ["green"]
        assert color["description"] == "Primary colors Cool colors"

    def test_oneof_discriminator_required_promoted(self) -> None:
        """A discriminator required by every branch is promoted and excluded
        from the exclusivity hint."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "oneOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "kind": {"const": "url"},
                                    "url": {"type": "string"},
                                },
                                "required": ["kind", "url"],
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "kind": {"const": "path"},
                                    "path": {"type": "string"},
                                },
                                "required": ["kind", "path"],
                            },
                        ],
                        "description": "pick a target",
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        target = result["properties"]["target"]
        assert target["type"] == "object"
        assert set(target["properties"]["kind"]["enum"]) == {"url", "path"}
        assert target["required"] == ["kind"]
        assert "kind" not in target["description"]
        assert "(url)" in target["description"]
        assert "(path)" in target["description"]

    def test_anyof_non_shared_required_not_promoted(self) -> None:
        """Branch-specific required fields stay dropped — forcing them together
        would require mutually-exclusive parameters simultaneously."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "filter": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "op": {"const": "eq"},
                                    "field": {"type": "string"},
                                },
                                "required": ["op", "field"],
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "op": {"const": "range"},
                                    "min": {"type": "number"},
                                },
                                "required": ["op", "min"],
                            },
                        ],
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        filter_prop = result["properties"]["filter"]
        assert filter_prop["type"] == "object"
        assert filter_prop["required"] == ["op"]
        assert "field" not in filter_prop["required"]
        assert "min" not in filter_prop["required"]

    def test_oneof_all_shared_required_skips_empty_hint(self) -> None:
        """When common-required exclusion leaves no distinguishing group, the
        exclusivity hint is dropped instead of emitting meaningless groups."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "target": {
                        "oneOf": [
                            {
                                "type": "object",
                                "properties": {"kind": {"const": "url"}},
                                "required": ["kind"],
                            },
                            {
                                "type": "object",
                                "properties": {"kind": {"const": "path"}},
                                "required": ["kind"],
                            },
                        ],
                        "description": "pick a target",
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        target = result["properties"]["target"]
        assert target["type"] == "object"
        assert target["required"] == ["kind"]
        assert target["description"] == "pick a target"
        assert "group" not in target["description"]

    def test_oneof_single_object_branch_kept(self) -> None:
        """A lone object branch next to a null branch is still selected."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "item": {
                        "oneOf": [
                            {
                                "type": "object",
                                "properties": {"id": {"type": "string"}},
                            },
                            {"type": "null"},
                        ]
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        item = result["properties"]["item"]
        assert item["type"] == "object"
        assert "id" in item["properties"]


class TestAllOf:
    """allOf normalization."""

    def test_allof_single_branch(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "item": {
                        "allOf": [
                            {"type": "object", "properties": {"id": {"type": "string"}}}
                        ],
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
                                "properties": {
                                    "name": {"type": "string"},
                                    "email": {"type": "string"},
                                },
                                "required": ["name", "email"],
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "age": {"type": "integer"},
                                    "role": {"type": "string"},
                                },
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
                            {
                                "type": "object",
                                "properties": {"a": {"type": "string"}},
                                "required": ["a"],
                            },
                            {
                                "type": "object",
                                "properties": {"b": {"type": "string"}},
                                "required": ["a", "b"],
                            },
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

    def test_allof_same_property_enum_intersection(self) -> None:
        """Redefined allOf properties intersect instead of overriding."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "item": {
                        "allOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "color": {
                                        "type": "string",
                                        "enum": ["red", "green"],
                                    }
                                },
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "color": {
                                        "type": "string",
                                        "enum": ["green", "blue"],
                                    }
                                },
                            },
                        ]
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        color = result["properties"]["item"]["properties"]["color"]
        assert color["enum"] == ["green"]

    def test_allof_same_property_closed_plus_open_keeps_closed(self) -> None:
        """A closed enum conjoined with an open type keeps the closed set."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "item": {
                        "allOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "mode": {
                                        "type": "string",
                                        "enum": ["auto", "manual"],
                                    }
                                },
                            },
                            {
                                "type": "object",
                                "properties": {"mode": {"type": "string"}},
                            },
                        ]
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        mode = result["properties"]["item"]["properties"]["mode"]
        assert mode["enum"] == ["auto", "manual"]


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
                "definitions": {
                    "Item": {"type": "string", "description": "An item ID"}
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["properties"]["item"]["type"] == "string"
        assert "definitions" not in result

    def test_ref_sibling_metadata_preserved(self) -> None:
        """Sibling keys next to ``$ref`` (e.g. an overriding description) must
        survive inlining — matching the inbound ``flatten_json_schema``
        behavior; dropping them hides field guidance from the LLM."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "user": {
                        "$ref": "#/$defs/User",
                        "description": "The target user",
                    }
                },
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
        user_prop = result["properties"]["user"]
        assert user_prop["type"] == "object"
        assert "name" in user_prop["properties"]
        assert user_prop["description"] == "The target user"

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

    def test_top_level_no_object_branch_falls_back(self) -> None:
        """Non-object-only branches fall back to a permissive empty schema."""
        schema = _wrap(
            {"anyOf": [{"type": "string"}, {"type": "null"}]}
        )
        result = _params(normalize_tool_schema(schema))
        assert result["type"] == "object"
        assert result["properties"] == {}

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

    def test_top_level_single_branch_preserves_outer_metadata(self) -> None:
        """Outer title/examples survive single-object-branch extraction."""
        schema = _wrap(
            {
                "title": "Target",
                "examples": [{"kind": "url"}],
                "description": "Pick a target",
                "anyOf": [
                    {"type": "object", "properties": {"url": {"type": "string"}}},
                    {"type": "null"},
                ],
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["type"] == "object"
        assert result["title"] == "Target"
        assert result["examples"] == [{"kind": "url"}]
        assert result["description"] == "Pick a target"

    def test_top_level_null_plus_object_preserves_outer_metadata(self) -> None:
        """Outer title/description survive when a lone object branch follows null."""
        schema = _wrap(
            {
                "title": "Target",
                "description": "Pick a target",
                "anyOf": [
                    {"type": "null"},
                    {"type": "object", "properties": {"url": {"type": "string"}}},
                ],
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["type"] == "object"
        assert result["title"] == "Target"
        assert result["description"] == "Pick a target"

    def test_top_level_allof_preserves_outer_metadata(self) -> None:
        """Outer title/description survive allOf object-branch merging."""
        schema = _wrap(
            {
                "title": "User",
                "description": "User data",
                "allOf": [
                    {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                    },
                    {
                        "type": "object",
                        "properties": {"age": {"type": "integer"}},
                    },
                ],
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["type"] == "object"
        assert result["title"] == "User"
        assert result["description"] == "User data"
        assert "name" in result["properties"]
        assert "age" in result["properties"]

    def test_top_level_oneof_multi_object_branches(self) -> None:
        schema = _wrap(
            {
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {"index": {"type": "integer"}},
                        "required": ["index"],
                    },
                    {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                        },
                        "required": ["x", "y"],
                    },
                ]
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["type"] == "object"
        assert set(result["properties"]) == {"index", "x", "y"}
        # Union alternatives must not be forced together.
        assert "required" not in result
        assert "oneOf" not in result
        assert "exactly one group" in result["description"]
        assert "(x, y)" in result["description"]

    def test_top_level_anyof_multi_object_branches_wording(self) -> None:
        """anyOf admits at least one group — the hint wording must say so."""
        schema = _wrap(
            {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {"index": {"type": "integer"}},
                        "required": ["index"],
                    },
                    {
                        "type": "object",
                        "properties": {"x": {"type": "number"}},
                        "required": ["x"],
                    },
                ]
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["type"] == "object"
        assert "at least one of these groups" in result["description"]
        assert "exactly one" not in result["description"]

    def test_top_level_allof_multi_object_branches(self) -> None:
        schema = _wrap(
            {
                "allOf": [
                    {
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                        "required": ["id"],
                    },
                    {
                        "type": "object",
                        "properties": {
                            "tags": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["tags"],
                    },
                ]
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["type"] == "object"
        assert set(result["properties"]) == {"id", "tags"}
        assert set(result["required"]) == {"id", "tags"}
        assert "allOf" not in result


class TestNestedSchemas:
    """Nested objects and arrays."""

    def test_nested_object_nullable(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "outer": {
                        "type": "object",
                        "properties": {
                            "inner": {"anyOf": [{"type": "string"}, {"type": "null"}]}
                        },
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
                        "properties": {
                            "value": {"anyOf": [{"type": "number"}, {"type": "null"}]}
                        },
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
                "properties": {"config": {"properties": {"key": {"type": "string"}}}},
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


class TestAnthropicStrip:
    """Anthropic-specific unsupported JSON Schema keyword stripping."""

    def test_strips_minimum_maximum_for_claude(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 10,
                        "description": "Result count",
                    }
                },
            }
        )
        result = _params(
            normalize_tool_schema(schema, model_name="claude-sonnet-4-20250514")
        )
        prop = result["properties"]["count"]
        assert "minimum" not in prop
        assert "maximum" not in prop
        assert "range: 0\u201310" in prop["description"]

    def test_preserves_keywords_for_non_claude(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "minimum": 0, "maximum": 10}
                },
            }
        )
        result = _params(normalize_tool_schema(schema, model_name="gpt-4o"))
        prop = result["properties"]["count"]
        assert prop["minimum"] == 0
        assert prop["maximum"] == 10

    def test_preserves_keywords_when_no_model(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "minimum": 0, "maximum": 10}
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        prop = result["properties"]["count"]
        assert prop["minimum"] == 0
        assert prop["maximum"] == 10

    def test_strips_title_default(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "title": "File Path",
                        "default": ".",
                        "description": "Target path",
                    }
                },
            }
        )
        result = _params(
            normalize_tool_schema(schema, model_name="claude-sonnet-4-20250514")
        )
        prop = result["properties"]["path"]
        assert "title" not in prop
        assert "default" not in prop
        assert "default: ." in prop["description"]

    def test_strips_max_items(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 20,
                        "description": "URLs",
                    }
                },
            }
        )
        result = _params(
            normalize_tool_schema(
                schema, model_name="anthropic/claude-sonnet-4-20250514"
            )
        )
        prop = result["properties"]["urls"]
        assert "maxItems" not in prop
        assert "items: 0\u201320" in prop["description"]

    def test_strips_pattern_format(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "format": "email",
                        "pattern": "^[a-z]+@",
                        "description": "Email address",
                    }
                },
            }
        )
        result = _params(
            normalize_tool_schema(schema, model_name="claude-sonnet-4-20250514")
        )
        prop = result["properties"]["email"]
        assert "format" not in prop
        assert "pattern" not in prop
        assert "format: email" in prop["description"]
        assert "pattern: ^[a-z]+@" in prop["description"]

    def test_strips_nested_properties(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "config": {
                        "type": "object",
                        "properties": {
                            "timeout": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 300,
                                "default": 30,
                                "description": "Timeout in seconds",
                            }
                        },
                    }
                },
            }
        )
        result = _params(
            normalize_tool_schema(schema, model_name="claude-sonnet-4-20250514")
        )
        timeout = result["properties"]["config"]["properties"]["timeout"]
        assert "minimum" not in timeout
        assert "maximum" not in timeout
        assert "default" not in timeout
        assert "range: 1\u2013300" in timeout["description"]

    def test_strips_items_format(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string", "format": "uri"},
                    }
                },
            }
        )
        result = _params(
            normalize_tool_schema(schema, model_name="claude-sonnet-4-20250514")
        )
        items = result["properties"]["urls"]["items"]
        assert "format" not in items

    def test_no_description_creates_hint(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "val": {"type": "integer", "minimum": 0, "maximum": 100}
                },
            }
        )
        result = _params(
            normalize_tool_schema(schema, model_name="claude-sonnet-4-20250514")
        )
        prop = result["properties"]["val"]
        assert prop["description"] == "(range: 0\u2013100)"

    def test_does_not_mutate_original_with_model(self) -> None:
        import copy

        original = _wrap(
            {
                "type": "object",
                "properties": {"x": {"type": "integer", "minimum": 0, "maximum": 10}},
            }
        )
        frozen = copy.deepcopy(original)
        normalize_tool_schema(original, model_name="claude-sonnet-4-20250514")
        assert original == frozen

    def test_anthropic_provider_prefix(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"n": {"type": "integer", "minimum": 1, "title": "N"}},
            }
        )
        result = _params(
            normalize_tool_schema(
                schema, model_name="anthropic/claude-sonnet-4-20250514"
            )
        )
        prop = result["properties"]["n"]
        assert "minimum" not in prop
        assert "title" not in prop


class TestOrphanRequiredPruning:
    """Prune required entries that reference fields absent from properties.

    Gemini/Vertex AI and OpenAI strict mode reject schemas with orphan required.
    """

    def test_top_level_orphan_pruned(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["title", "body", "repo", "owner"],
            }
        )
        result = _params(normalize_tool_schema(schema, model_name="gemini-2.5-flash"))
        assert result["required"] == ["title", "body"]

    def test_nested_orphan_pruned(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "config": {
                        "type": "object",
                        "properties": {"timeout": {"type": "integer"}},
                        "required": ["timeout", "retries", "priority"],
                    }
                },
                "required": ["config"],
            }
        )
        result = _params(normalize_tool_schema(schema, model_name="gemini-2.5-flash"))
        assert result["properties"]["config"]["required"] == ["timeout"]

    def test_all_orphan_removes_required_key(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["a", "b", "c"],
            }
        )
        result = _params(normalize_tool_schema(schema, model_name="gemini-2.5-flash"))
        assert "required" not in result

    def test_clean_schema_unchanged(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "a": {"type": "string"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            }
        )
        result = _params(normalize_tool_schema(schema, model_name="gemini-2.5-flash"))
        assert result["required"] == ["a", "b"]

    def test_no_required_key_unaffected(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"x": {"type": "string"}},
            }
        )
        result = _params(normalize_tool_schema(schema, model_name="gemini-2.5-flash"))
        assert "required" not in result

    def test_works_for_non_gemini_models(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["a", "missing"],
            }
        )
        result = _params(normalize_tool_schema(schema, model_name="gpt-4o"))
        assert result["required"] == ["a"]

    def test_allof_merge_orphan_pruned(self) -> None:
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "item": {
                        "allOf": [
                            {
                                "type": "object",
                                "properties": {"name": {"type": "string"}},
                                "required": ["name", "id"],
                            },
                            {
                                "type": "object",
                                "properties": {"age": {"type": "integer"}},
                                "required": ["age"],
                            },
                        ]
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        item = result["properties"]["item"]
        assert "id" not in item.get("required", [])
        assert "name" in item.get("required", [])
        assert "age" in item.get("required", [])

    def test_array_items_object_orphan_pruned(self) -> None:
        """Orphan required inside array items object schema are pruned."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"label": {"type": "string"}},
                            "required": ["label", "color"],
                        },
                    }
                },
                "required": ["tags"],
            }
        )
        result = _params(normalize_tool_schema(schema))
        items_schema = result["properties"]["tags"]["items"]
        assert items_schema["required"] == ["label"]

    def test_deeply_nested_three_levels_orphan(self) -> None:
        """Orphan required pruning works at 3+ nesting levels."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "level1": {
                        "type": "object",
                        "properties": {
                            "level2": {
                                "type": "object",
                                "properties": {
                                    "level3": {
                                        "type": "object",
                                        "properties": {"val": {"type": "string"}},
                                        "required": ["val", "ghost"],
                                    }
                                },
                                "required": ["level3"],
                            }
                        },
                        "required": ["level2", "phantom"],
                    }
                },
                "required": ["level1"],
            }
        )
        result = _params(normalize_tool_schema(schema))
        l1 = result["properties"]["level1"]
        assert l1["required"] == ["level2"]
        l2 = l1["properties"]["level2"]
        assert l2["required"] == ["level3"]
        l3 = l2["properties"]["level3"]
        assert l3["required"] == ["val"]

    def test_duplicate_required_entries_deduplication(self) -> None:
        """Duplicate entries in required are preserved but orphans removed."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x", "x", "missing"],
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert result["required"] == ["x", "x"]

    def test_anthropic_model_still_prunes_orphan(self) -> None:
        """Orphan pruning works even when Anthropic strip pass follows."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {"name": {"type": "string", "minLength": 1}},
                "required": ["name", "absent"],
            }
        )
        result = _params(
            normalize_tool_schema(schema, model_name="claude-sonnet-4-20250514")
        )
        assert result["required"] == ["name"]

    def test_missing_local_ref_degrades(self) -> None:
        """An unresolvable local $ref degrades instead of leaking raw pointer."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {
                    "x": {"$ref": "#/$defs/Missing", "description": "external"},
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert "$ref" not in str(result)
        x = result["properties"]["x"]
        assert x["type"] == "object"
        assert x.get("additionalProperties") is True
        assert x.get("description") == "external"

    def test_external_url_ref_degrades(self) -> None:
        """An external URL $ref is degraded when no local defs exist."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {"z": {"$ref": "https://example.com/schema.json#/X"}},
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert "$ref" not in str(result)
        assert result["properties"]["z"]["type"] == "object"

    def test_missing_ref_scalar_type_kept(self) -> None:
        """A missing $ref with a declared scalar type keeps that type."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {"n": {"$ref": "#/$defs/Missing", "type": "integer"}},
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert "$ref" not in str(result)
        assert result["properties"]["n"] == {"type": "integer"}

    def test_deep_ref_chain_bounded(self) -> None:
        """Circular $ref chains still stop at the depth bound."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {"next": {"$ref": "#/$defs/Node"}},
                "$defs": {
                    "Node": {
                        "type": "object",
                        "properties": {"next": {"$ref": "#/$defs/Node"}},
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert "$ref" not in str(result)
        assert result["properties"]["next"]["type"] == "object"

    def test_valid_ref_still_resolves(self) -> None:
        """Resolvable $refs keep working after the degradation fallback."""
        schema = _wrap(
            {
                "type": "object",
                "properties": {"addr": {"$ref": "#/$defs/Addr"}},
                "$defs": {
                    "Addr": {
                        "type": "object",
                        "properties": {"street": {"type": "string"}},
                    }
                },
            }
        )
        result = _params(normalize_tool_schema(schema))
        assert "$ref" not in str(result)
        assert "street" in str(result)

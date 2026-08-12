from myrm_agent_harness.toolkits.mcp.schema import (
    collapse_const_unions,
    flatten_json_schema,
    flatten_top_level_composite,
)

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
            {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
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


def test_flatten_top_level_composite_allof_same_property_intersects():
    """allOf redefined properties intersect, not union."""
    schema = {
        "allOf": [
            {
                "type": "object",
                "properties": {
                    "color": {"type": "string", "enum": ["red", "green"]},
                    "bright": {"type": "boolean"},
                },
            },
            {
                "type": "object",
                "properties": {"color": {"type": "string", "enum": ["green", "blue"]}},
            },
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["properties"]["color"]["enum"] == ["green"]
    assert result["properties"]["bright"]["type"] == "boolean"


def test_flatten_top_level_composite_allof_closed_plus_open_keeps_closed():
    """A closed enum conjoined with an open type keeps the closed set."""
    schema = {
        "allOf": [
            {
                "type": "object",
                "properties": {"mode": {"type": "string", "enum": ["auto", "manual"]}},
                "required": ["mode"],
            },
            {"type": "object", "properties": {"mode": {"type": "string"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["properties"]["mode"]["enum"] == ["auto", "manual"]


def test_flatten_top_level_composite_allof_disjoint_enums_keep_first():
    """An empty allOf intersection keeps the first definition (no empty enum)."""
    schema = {
        "allOf": [
            {"type": "object", "properties": {"mode": {"const": "on"}}},
            {"type": "object", "properties": {"mode": {"const": "off"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["properties"]["mode"] == {"const": "on"}


def test_flatten_top_level_composite_anyof_constraint_wording():
    """anyOf alternatives admit at least one group (real anyOf semantics)."""
    schema = {
        "anyOf": [
            {"type": "object", "properties": {"a": {"type": "string"}}},
            {"type": "object", "properties": {"b": {"type": "string"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert "at least one" in result["description"]
    assert "(a)" in result["description"]
    assert "(b)" in result["description"]


def test_flatten_top_level_composite_oneof_constraint_wording():
    """oneOf alternatives admit exactly one group."""
    schema = {
        "oneOf": [
            {"type": "object", "properties": {"a": {"type": "string"}}},
            {"type": "object", "properties": {"b": {"type": "string"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert "mutually exclusive" in result["description"]
    assert "exactly one" in result["description"]


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
            {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
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
                "properties": {"opts": {"type": "array", "items": {"type": "string"}}},
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


def test_flatten_top_level_composite_const_plus_open_type_union():
    """A const/enum branch unioned with an open type widens to the open type."""
    schema = {
        "oneOf": [
            {"type": "object", "properties": {"mode": {"const": "auto"}}},
            {"type": "object", "properties": {"mode": {"type": "string"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    mode = result["properties"]["mode"]
    assert "const" not in mode
    assert "enum" not in mode
    assert mode["type"] == "string"


def test_flatten_top_level_composite_enum_plus_open_type_union():
    """An enum branch unioned with an open type widens to the open type."""
    schema = {
        "anyOf": [
            {"type": "object", "properties": {"v": {"enum": ["a", "b"]}}},
            {"type": "object", "properties": {"v": {"type": "integer"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    v = result["properties"]["v"]
    assert "const" not in v and "enum" not in v
    assert v["type"] == "integer"


def test_flatten_top_level_composite_union_keeps_default():
    """A shared default on the merged property is preserved."""
    schema = {
        "anyOf": [
            {
                "type": "object",
                "properties": {"action": {"const": "up", "default": "up"}},
            },
            {"type": "object", "properties": {"action": {"const": "down"}}},
        ],
    }
    result = flatten_top_level_composite(schema)
    assert result["properties"]["action"]["default"] == "up"
    assert result["properties"]["action"]["enum"] == ["up", "down"]


# ---------------------------------------------------------------------------
# Property-level const-union collapsing tests
# ---------------------------------------------------------------------------


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


def test_collapse_const_unions_boolean_enum():
    """True/False const pairs collapse into a boolean enum."""
    result = collapse_const_unions({"anyOf": [{"const": True}, {"const": False}]})
    assert result == {"type": "boolean", "enum": [True, False]}


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


def test_collapse_const_unions_mixed_composite_keys_untouched():
    """A node with more than one composite keyword is never collapsed."""
    schema = {
        "anyOf": [{"const": "red"}, {"const": "green"}],
        "allOf": [{"type": "string"}, {"minLength": 1}],
    }
    assert collapse_const_unions(schema) == schema


def test_collapse_const_unions_duplicate_const_deduplicated():
    """Repeated const values collapse into a deduplicated enum."""
    result = collapse_const_unions(
        {"anyOf": [{"const": "red"}, {"const": "red"}, {"const": "green"}]}
    )
    assert result == {"type": "string", "enum": ["red", "green"]}


def test_collapse_const_unions_outer_type_mismatch_rejected():
    """An outer type conflicting with the const union blocks the fold."""
    schema = {
        "type": "object",
        "anyOf": [{"const": "red"}, {"const": "green"}],
    }
    assert collapse_const_unions(schema) == schema


def test_collapse_const_unions_outer_type_matching_folded():
    """An outer type matching the const union still folds."""
    result = collapse_const_unions(
        {"type": "string", "anyOf": [{"const": "red"}, {"const": "green"}]}
    )
    assert result == {"type": "string", "enum": ["red", "green"]}


def test_collapse_const_unions_enum_data_values_not_rewritten():
    """enum arrays hold literal data — nested objects are never collapsed."""
    schema = {
        "type": "object",
        "properties": {"mode": {"enum": [{"anyOf": [{"const": "x"}]}, {"v": 2}]}},
    }
    result = collapse_const_unions(schema)
    assert result["properties"]["mode"]["enum"] == [
        {"anyOf": [{"const": "x"}]},
        {"v": 2},
    ]


def test_collapse_const_unions_keeps_examples_metadata():
    """Outer examples are carried onto the folded enum replacement."""
    result = collapse_const_unions(
        {
            "examples": ["red", "green"],
            "anyOf": [{"const": "red"}, {"const": "green"}],
        }
    )
    assert result["examples"] == ["red", "green"]
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
                "properties": {
                    "action": {"const": "click"},
                    "idx": {"type": "integer"},
                },
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

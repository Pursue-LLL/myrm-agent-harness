"""Tests for property-key sanitization (key_sanitize.py).

Covers the rename/restore symmetry that provider key-pattern compliance
depends on: non-conforming keys (``issue_class~neq``, ``meta[x]``) are
renamed deterministically for the LLM-facing schema, and dispatch-time
restoration turns them back into the original wire names before the MCP
call.
"""

from myrm_agent_harness.toolkits.mcp.schema.key_sanitize import (
    restore_property_keys,
    sanitize_property_key,
    sanitize_property_keys,
)


def test_sanitize_property_key_dot_underscore():
    assert sanitize_property_key("meta.field") == "meta_field"


def test_sanitize_property_key_tilde():
    assert sanitize_property_key("issue_class~neq") == "issue_class_neq"


def test_sanitize_property_key_brackets():
    assert sanitize_property_key("meta[filter]") == "meta_filter"


def test_sanitize_property_key_unicode():
    assert sanitize_property_key("名前") == "param"


def test_sanitize_property_key_all_bad_chars():
    assert sanitize_property_key("~~") == "param"


def test_sanitize_property_key_truncates_long():
    key = "a" * 100
    assert len(sanitize_property_key(key)) == 64


def test_sanitize_property_keys_flat():
    schema = {
        "type": "object",
        "properties": {"issue_class~neq": {"type": "string"}, "ok_key": {"type": "integer"}},
    }
    result, restore_map = sanitize_property_keys(schema)
    assert "issue_class~neq" not in result["properties"]
    assert "issue_class_neq" in result["properties"]
    assert "ok_key" in result["properties"]
    assert restore_map == {"issue_class_neq": "issue_class~neq"}


def test_sanitize_property_keys_required_synced():
    schema = {
        "type": "object",
        "properties": {"meta[x]": {"type": "string"}, "name": {"type": "string"}},
        "required": ["meta[x]", "name"],
    }
    result, restore_map = sanitize_property_keys(schema)
    assert result["required"] == ["meta_x", "name"]
    assert restore_map == {"meta_x": "meta[x]"}


def test_sanitize_property_keys_nested_recursive():
    schema = {
        "type": "object",
        "properties": {
            "outer": {
                "type": "object",
                "properties": {"inner~key": {"type": "string"}},
            }
        },
    }
    result, restore_map = sanitize_property_keys(schema)
    assert "inner~key" not in str(result)
    inner = result["properties"]["outer"]["properties"]
    assert "inner_key" in inner
    assert restore_map == {"outer.inner_key": "inner~key"}


def test_sanitize_property_keys_collision_deterministic():
    """Colliding renames get numeric suffixes deterministically."""
    schema = {
        "type": "object",
        "properties": {"a.b": {"type": "string"}, "a_b": {"type": "integer"}},
    }
    result, restore_map = sanitize_property_keys(schema)
    props = result["properties"]
    assert set(props) == {"a_b", "a_b_2"}
    # ``a_b`` is already conforming (kept); ``a.b`` is renamed away to ``a_b_2``.
    assert restore_map == {"a_b_2": "a.b"}


def test_sanitize_property_keys_no_conforming_keys_passthrough():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b_1": {"type": "integer"}},
        "required": ["a"],
    }
    result, restore_map = sanitize_property_keys(schema)
    assert restore_map == {}
    assert result is schema


def test_restore_property_keys_flat():
    restore_map = {"issue_class_neq": "issue_class~neq"}
    args = {"issue_class_neq": "open"}
    assert restore_property_keys(args, restore_map) == {"issue_class~neq": "open"}


def test_restore_property_keys_nested():
    restore_map = {"outer.meta_x": "meta[x]", "meta_x": "meta[x]"}
    args = {"outer": {"meta_x": 1}, "list": [{"meta_x": 2}]}
    result = restore_property_keys(args, restore_map)
    assert result == {"outer": {"meta[x]": 1}, "list": [{"meta_x": 2}]}


def test_restore_property_keys_empty_map_passthrough():
    args = {"a": 1, "b": {"c": 2}}
    assert restore_property_keys(args, {}) is args


def test_restore_property_keys_unmapped_keys_untouched():
    args = {"keep": "x", "nested": {"also_keep": 1}}
    result = restore_property_keys(args, {"other": "mapped"})
    assert result == args


def test_restore_property_keys_path_aware_no_cross_layer_collision():
    """A nested conforming key equal to a renamed top-level key is kept intact."""
    restore_map = {"meta__status__eq": "meta.<status>[eq]"}
    args = {
        "meta__status__eq": "open",
        "filters": {"meta__status__eq": "x"},
    }
    result = restore_property_keys(args, restore_map)
    assert result == {
        "meta.<status>[eq]": "open",
        "filters": {"meta__status__eq": "x"},
    }


def test_rename_restore_roundtrip_symmetry():
    """Rename then restore yields the original wire-name argument tree."""
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "filter~status": {"type": "string"},
            "meta[page]": {"type": "integer"},
            "nested": {
                "type": "object",
                "properties": {"deep~key": {"type": "string"}},
            },
        },
    }
    _sanitized, restore_map = sanitize_property_keys(schema)
    assert restore_map == {
        "filter_status": "filter~status",
        "meta_page": "meta[page]",
        "nested.deep_key": "deep~key",
    }
    model_args = {
        "query": "abc",
        "filter_status": "open",
        "meta_page": 2,
        "nested": {"deep_key": "v"},
    }
    restored = restore_property_keys(model_args, restore_map)
    assert restored == {
        "query": "abc",
        "filter~status": "open",
        "meta[page]": 2,
        "nested": {"deep~key": "v"},
    }


def test_rename_restore_cross_layer_collision_roundtrip():
    """Top-level rename and same-named nested conforming key round-trip correctly."""
    schema = {
        "type": "object",
        "properties": {
            "meta.<status>[eq]": {"type": "string"},
            "filters": {
                "type": "object",
                "properties": {"meta__status__eq": {"type": "string"}},
            },
        },
    }
    _sanitized, restore_map = sanitize_property_keys(schema)
    assert restore_map == {"meta__status__eq": "meta.<status>[eq]"}
    model_args = {
        "meta__status__eq": "open",
        "filters": {"meta__status__eq": "x"},
    }
    restored = restore_property_keys(model_args, restore_map)
    assert restored == {
        "meta.<status>[eq]": "open",
        "filters": {"meta__status__eq": "x"},
    }

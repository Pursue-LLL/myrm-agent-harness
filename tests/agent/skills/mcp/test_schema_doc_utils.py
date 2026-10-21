"""Unit tests for MCP JSON Schema → markdown documentation utilities.

Covers build_params_section, extract_schema_constraints, build_call_example,
normalize_input_schema, and TOOL_DOC_TEMPLATE rendering edge paths.
"""

from __future__ import annotations

from types import SimpleNamespace

from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import (
    TOOL_DOC_TEMPLATE,
    build_call_example,
    build_params_section,
    extract_schema_constraints,
    normalize_input_schema,
)


class TestBuildParamsSection:
    def test_empty_schema_returns_no_params(self) -> None:
        assert build_params_section({}) == "## Parameters\n\nNo parameters required."
        assert build_params_section(None) == "## Parameters\n\nNo parameters required."
        assert build_params_section({"type": "object"}) == "## Parameters\n\nNo parameters required."

    def test_renders_required_and_optional_tags(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Departure date"},
                "limit": {"type": "integer", "description": "Max rows"},
            },
            "required": ["date"],
        }
        section = build_params_section(schema)
        assert "### date **(required)**" in section
        assert "### limit (optional)" in section
        assert "- **Type**: `string`" in section
        assert "- **Description**: Departure date" in section

    def test_non_dict_param_info_skipped(self) -> None:
        schema = {"type": "object", "properties": {"weird": "not-a-dict"}}
        section = build_params_section(schema)
        assert "### weird" not in section

    def test_no_description_default(self) -> None:
        schema = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
        }
        section = build_params_section(schema)
        assert "- **Description**: No description" in section


class TestExtractSchemaConstraints:
    def test_all_numeric_and_length_renderers(self) -> None:
        param = {
            "minimum": 1,
            "maximum": 10,
            "exclusiveMinimum": 0,
            "exclusiveMaximum": 11,
            "minLength": 2,
            "maxLength": 8,
            "minItems": 1,
            "maxItems": 5,
        }
        lines = extract_schema_constraints(param)
        joined = "\n".join(lines)
        assert "Minimum" in joined
        assert "Maximum" in joined
        assert "Exclusive minimum" in joined
        assert "Exclusive maximum" in joined
        assert "Min length" in joined
        assert "Max length" in joined
        assert "Min items" in joined
        assert "Max items" in joined

    def test_format_default_pattern(self) -> None:
        param = {"format": "date", "default": "2026-01-01", "pattern": "^\\d{4}$"}
        lines = extract_schema_constraints(param)
        joined = "\n".join(lines)
        assert "Format" in joined
        assert "Default" in joined
        assert "Pattern (regex)" in joined

    def test_enum_and_examples(self) -> None:
        param = {"enum": ["a", "b"], "examples": [1, 2, 3]}
        lines = extract_schema_constraints(param)
        joined = "\n".join(lines)
        assert "Allowed values" in joined
        assert "`a`" in joined
        assert "Examples" in joined

    def test_examples_truncated_to_five(self) -> None:
        param = {"examples": list(range(8))}
        lines = extract_schema_constraints(param)
        assert lines[0].count("`") == 10  # 5 values, each wrapped in backticks

    def test_items_with_enum(self) -> None:
        param = {"items": {"type": "string", "enum": ["x", "y"]}}
        lines = extract_schema_constraints(param)
        assert "- **Item type**: `string` (allowed: `x`, `y`)" in lines

    def test_items_without_enum(self) -> None:
        param = {"items": {"type": "integer"}}
        lines = extract_schema_constraints(param)
        assert "- **Item type**: `integer`" in lines

    def test_non_dict_items_ignored(self) -> None:
        assert extract_schema_constraints({"items": "not-a-dict"}) == []

    def test_empty_param_returns_empty(self) -> None:
        assert extract_schema_constraints({}) == []


class TestBuildCallExample:
    def test_string_without_example(self) -> None:
        schema = {"properties": {"name": {"type": "string"}}, "required": ["name"]}
        assert build_call_example(schema) == 'name="..."'

    def test_number_and_boolean_and_other(self) -> None:
        schema = {
            "properties": {
                "count": {"type": "integer"},
                "ratio": {"type": "number"},
                "enabled": {"type": "boolean"},
                "tags": {"type": "array"},
            },
            "required": ["count", "ratio", "enabled", "tags"],
        }
        result = build_call_example(schema)
        assert "count=0" in result
        assert "ratio=0" in result
        assert "enabled=True" in result
        assert "tags=..." in result

    def test_example_priority_over_type_default(self) -> None:
        schema = {
            "properties": {"n": {"type": "integer", "examples": [42]}},
            "required": ["n"],
        }
        assert build_call_example(schema) == "n=42"

    def test_non_dict_param_info_skipped(self) -> None:
        schema = {"properties": {"weird": "x"}, "required": ["weird"]}
        assert build_call_example(schema) == ""

    def test_no_schema(self) -> None:
        assert build_call_example(None) == ""
        assert build_call_example("nope") == ""


class TestNormalizeInputSchema:
    def test_none_returns_empty(self) -> None:
        assert normalize_input_schema(None) == {}

    def test_dict_passthrough(self) -> None:
        schema = {"type": "object"}
        assert normalize_input_schema(schema) is schema

    def test_pydantic_model_uses_model_json_schema(self) -> None:
        model = SimpleNamespace(model_json_schema=lambda: {"type": "object", "properties": {"x": {}}})
        assert normalize_input_schema(model)["properties"] == {"x": {}}

    def test_model_without_schema_method(self) -> None:
        assert normalize_input_schema(SimpleNamespace(no_schema=1)) == {}

    def test_model_json_schema_non_dict_result(self) -> None:
        model = SimpleNamespace(model_json_schema=lambda: "not-a-dict")
        assert normalize_input_schema(model) == {}


class TestToolDocTemplateRendering:
    def test_renders_call_example(self) -> None:
        rendered = TOOL_DOC_TEMPLATE.format(
            tool_name="search",
            skill_name="demo_skill",
            tool_desc="Search.",
            params_section="## Parameters\n\nNo parameters required.",
            call_example='query="..."',
        )
        assert 'result = await search(query="...")' in rendered

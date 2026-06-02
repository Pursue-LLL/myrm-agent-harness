"""Tests for schema-aware JSON string coercion in tool args guard.

Validates that the _coerce_stringified_json logic correctly:
- Parses JSON strings for list/dict schema fields
- Preserves string-type fields even when they contain valid JSON
- Handles malformed JSON gracefully
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, Field


class _MockToolInput(BaseModel):
    paths: list[str] = Field(description="File paths")
    content: str = Field(description="String content")
    headers: dict[str, str] | None = Field(default=None, description="HTTP headers")
    name: str = Field(default="test", description="Name")


class _MockTool:
    args_schema = _MockToolInput


def _get_coercible_fields(tool: object) -> frozenset[str]:
    """Extracted logic matching base_agent._get_coercible_fields."""
    schema_cls = getattr(tool, "args_schema", None)
    if schema_cls is None:
        return frozenset()

    try:
        schema = schema_cls.model_json_schema()
    except Exception:
        return frozenset()

    fields: set[str] = set()
    for field_name, prop in schema.get("properties", {}).items():
        prop_type = prop.get("type")
        if prop_type in ("array", "object"):
            fields.add(field_name)
            continue
        for variant in prop.get("anyOf", []):
            if variant.get("type") in ("array", "object"):
                fields.add(field_name)
                break

    return frozenset(fields)


def _coerce_stringified_json(
    args: dict[str, object],
    coercible: frozenset[str],
) -> None:
    """Extracted logic matching base_agent._coerce_stringified_json."""
    for key in coercible:
        value = args.get(key)
        if not isinstance(value, str) or len(value) < 2:
            continue
        if value[0] not in ("[", "{"):
            continue
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (list, dict)):
                args[key] = parsed
        except (ValueError, json.JSONDecodeError):
            pass


class TestGetCoercibleFields:
    def test_detects_list_fields(self) -> None:
        fields = _get_coercible_fields(_MockTool())
        assert "paths" in fields

    def test_detects_optional_dict_fields(self) -> None:
        fields = _get_coercible_fields(_MockTool())
        assert "headers" in fields

    def test_excludes_string_fields(self) -> None:
        fields = _get_coercible_fields(_MockTool())
        assert "content" not in fields
        assert "name" not in fields

    def test_returns_empty_for_no_schema(self) -> None:
        class NoSchema:
            pass

        assert _get_coercible_fields(NoSchema()) == frozenset()


class TestCoerceStringifiedJson:
    def test_parses_stringified_list(self) -> None:
        coercible = frozenset({"paths"})
        args: dict[str, object] = {"paths": '["a.py", "b.py"]', "content": "hello"}
        _coerce_stringified_json(args, coercible)
        assert args["paths"] == ["a.py", "b.py"]
        assert args["content"] == "hello"

    def test_parses_stringified_dict(self) -> None:
        coercible = frozenset({"headers"})
        args: dict[str, object] = {"headers": '{"Content-Type": "application/json"}'}
        _coerce_stringified_json(args, coercible)
        assert args["headers"] == {"Content-Type": "application/json"}

    def test_preserves_string_fields_with_json_content(self) -> None:
        """Critical: string fields containing valid JSON must NOT be coerced."""
        coercible = frozenset({"paths"})
        args: dict[str, object] = {"content": '{"key": "value"}', "paths": ["a.py"]}
        _coerce_stringified_json(args, coercible)
        assert args["content"] == '{"key": "value"}'

    def test_handles_invalid_json(self) -> None:
        coercible = frozenset({"paths"})
        args: dict[str, object] = {"paths": "[not valid json"}
        _coerce_stringified_json(args, coercible)
        assert args["paths"] == "[not valid json"

    def test_ignores_non_string_values(self) -> None:
        coercible = frozenset({"paths"})
        args: dict[str, object] = {"paths": ["already", "a", "list"]}
        _coerce_stringified_json(args, coercible)
        assert args["paths"] == ["already", "a", "list"]

    def test_ignores_short_strings(self) -> None:
        coercible = frozenset({"paths"})
        args: dict[str, object] = {"paths": "["}
        _coerce_stringified_json(args, coercible)
        assert args["paths"] == "["

    def test_ignores_missing_keys(self) -> None:
        coercible = frozenset({"paths"})
        args: dict[str, object] = {"content": "hello"}
        _coerce_stringified_json(args, coercible)
        assert args == {"content": "hello"}

    def test_does_not_coerce_json_primitive(self) -> None:
        """JSON string containing a primitive (e.g. 'null', '42') should NOT be coerced."""
        coercible = frozenset({"paths"})
        args: dict[str, object] = {"paths": "null"}
        _coerce_stringified_json(args, coercible)
        assert args["paths"] == "null"


class TestEndToEnd:
    def test_coerce_then_pydantic_validates(self) -> None:
        """Full flow: stringified JSON -> coerce -> Pydantic validation succeeds."""
        tool = _MockTool()
        coercible = _get_coercible_fields(tool)
        args: dict[str, object] = {
            "paths": '["a.py", "b.py"]',
            "content": '{"key": "val"}',
        }
        _coerce_stringified_json(args, coercible)
        result = _MockToolInput(**args)
        assert result.paths == ["a.py", "b.py"]
        assert result.content == '{"key": "val"}'

    def test_without_coerce_pydantic_fails(self) -> None:
        """Without coerce, Pydantic rejects stringified list."""
        with pytest.raises(Exception):
            _MockToolInput(paths='["a.py", "b.py"]', content="hello")

"""Unit tests for StructuredExtractor.

Tests cover:
- Schema-to-Pydantic model conversion (object, array, nested, edge cases)
- JSON text extraction from LLM responses
- Schema complexity validation
- Full extraction flow with mocked LLM (both strategies)
- Disabled state handling
- Error handling
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from myrm_agent_harness.toolkits.browser.session.structured_extractor import (
    StructuredExtractor,
    _build_model,
    _extract_json_from_text,
    _json_type_to_python,
    _schema_to_pydantic,
    _validate_schema_complexity,
)


class TestSchemaToPydantic:
    """Tests for _schema_to_pydantic and _build_model."""

    def test_object_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        model = _schema_to_pydantic(schema)
        assert model is not None
        assert "name" in model.model_fields
        assert "age" in model.model_fields
        assert model.model_fields["name"].is_required()
        assert not model.model_fields["age"].is_required()

    def test_array_schema_top_level(self) -> None:
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "price": {"type": "string"},
                },
                "required": ["title", "price"],
            },
        }
        model = _schema_to_pydantic(schema)
        assert model is not None
        assert "items" in model.model_fields
        field = model.model_fields["items"]
        assert "list" in str(field.annotation).lower()

    def test_array_schema_simple_items(self) -> None:
        schema = {"type": "array", "items": {"type": "string"}}
        model = _schema_to_pydantic(schema)
        assert model is not None
        assert "items" in model.model_fields

    def test_nested_object_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "address": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "zip": {"type": "string"},
                    },
                },
            },
        }
        model = _schema_to_pydantic(schema)
        assert model is not None
        assert "address" in model.model_fields

    def test_array_field_in_object(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        }
        model = _schema_to_pydantic(schema)
        assert model is not None
        assert "tags" in model.model_fields

    def test_schema_without_type_defaults_to_object(self) -> None:
        schema = {"properties": {"name": {"type": "string"}}}
        model = _schema_to_pydantic(schema)
        assert model is not None
        assert "name" in model.model_fields

    def test_empty_schema_produces_model(self) -> None:
        schema: dict[str, Any] = {"type": "object", "properties": {}}
        model = _schema_to_pydantic(schema)
        assert model is not None
        assert len(model.model_fields) == 0

    def test_all_json_types(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "s": {"type": "string"},
                "n": {"type": "number"},
                "i": {"type": "integer"},
                "b": {"type": "boolean"},
            },
        }
        model = _schema_to_pydantic(schema)
        assert model is not None
        assert len(model.model_fields) == 4


class TestJsonTypeToPython:
    """Tests for _json_type_to_python."""

    def test_string(self) -> None:
        assert _json_type_to_python("f", {"type": "string"}) is str

    def test_number(self) -> None:
        assert _json_type_to_python("f", {"type": "number"}) is float

    def test_integer(self) -> None:
        assert _json_type_to_python("f", {"type": "integer"}) is int

    def test_boolean(self) -> None:
        assert _json_type_to_python("f", {"type": "boolean"}) is bool

    def test_unknown_defaults_to_string(self) -> None:
        assert _json_type_to_python("f", {"type": "unknown"}) is str

    def test_no_type_defaults_to_string(self) -> None:
        assert _json_type_to_python("f", {}) is str


class TestValidateSchemaComplexity:
    """Tests for _validate_schema_complexity."""

    def test_simple_schema_valid(self) -> None:
        schema = {"properties": {"a": {"type": "string"}, "b": {"type": "integer"}}}
        assert _validate_schema_complexity(schema) is True

    def test_too_many_properties(self) -> None:
        properties = {f"field_{i}": {"type": "string"} for i in range(51)}
        schema = {"properties": properties}
        assert _validate_schema_complexity(schema) is False

    def test_max_properties_ok(self) -> None:
        properties = {f"field_{i}": {"type": "string"} for i in range(50)}
        schema = {"properties": properties}
        assert _validate_schema_complexity(schema) is True

    def test_deep_nesting_rejected(self) -> None:
        schema: dict[str, Any] = {"type": "object", "properties": {"a": {"type": "string"}}}
        current = schema
        for i in range(6):
            nested: dict[str, Any] = {
                "type": "object",
                "properties": {f"level_{i}": {"type": "object", "properties": {"x": {"type": "string"}}}},
            }
            current["properties"]["deep"] = nested
            current = nested
        assert _validate_schema_complexity(schema) is False

    def test_array_items_checked(self) -> None:
        schema = {
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                }
            }
        }
        assert _validate_schema_complexity(schema) is True

    def test_empty_schema_valid(self) -> None:
        assert _validate_schema_complexity({}) is True


class TestExtractJsonFromText:
    """Tests for _extract_json_from_text."""

    def test_direct_json_object(self) -> None:
        result = _extract_json_from_text('{"name": "test"}')
        assert result == {"name": "test"}

    def test_direct_json_array(self) -> None:
        result = _extract_json_from_text('[{"name": "A"}, {"name": "B"}]')
        assert result == [{"name": "A"}, {"name": "B"}]

    def test_empty_array(self) -> None:
        result = _extract_json_from_text("[]")
        assert result == []

    def test_markdown_code_block_object(self) -> None:
        text = '```json\n{"title": "hello"}\n```'
        result = _extract_json_from_text(text)
        assert result == {"title": "hello"}

    def test_markdown_code_block_array(self) -> None:
        text = '```json\n[{"a": 1}]\n```'
        result = _extract_json_from_text(text)
        assert result == [{"a": 1}]

    def test_json_embedded_in_text(self) -> None:
        text = 'Here is the result: {"price": "$10"} end'
        result = _extract_json_from_text(text)
        assert result == {"price": "$10"}

    def test_array_embedded_in_text(self) -> None:
        text = 'Results: [{"x": 1}] done'
        result = _extract_json_from_text(text)
        assert result == [{"x": 1}]

    def test_no_json_returns_none(self) -> None:
        assert _extract_json_from_text("no json here") is None

    def test_invalid_json_returns_none(self) -> None:
        assert _extract_json_from_text("{invalid json}") is None

    def test_whitespace_handling(self) -> None:
        result = _extract_json_from_text("  \n  {\"key\": \"value\"}  \n  ")
        assert result == {"key": "value"}


class TestStructuredExtractorInit:
    """Tests for StructuredExtractor initialization and state."""

    def test_enabled_with_llm(self) -> None:
        mock_llm = MagicMock()
        extractor = StructuredExtractor(llm=mock_llm)
        assert extractor.enabled is True

    def test_disabled_without_llm(self) -> None:
        extractor = StructuredExtractor(llm=None)
        assert extractor.enabled is False


class TestStructuredExtractorExtract:
    """Tests for StructuredExtractor.extract() method."""

    @pytest.mark.asyncio
    async def test_disabled_returns_error(self) -> None:
        extractor = StructuredExtractor(llm=None)
        result = await extractor.extract(
            text="some text",
            schema={"type": "object", "properties": {"name": {"type": "string"}}},
        )
        assert "[Error]" in result
        assert "unavailable" in result

    @pytest.mark.asyncio
    async def test_complex_schema_returns_error(self) -> None:
        mock_llm = MagicMock()
        extractor = StructuredExtractor(llm=mock_llm)
        properties = {f"field_{i}": {"type": "string"} for i in range(51)}
        result = await extractor.extract(
            text="some text",
            schema={"type": "object", "properties": properties},
        )
        assert "[Error]" in result
        assert "too complex" in result

    @pytest.mark.asyncio
    async def test_strategy1_object_success(self) -> None:
        mock_llm = MagicMock()
        mock_model_instance = MagicMock(spec=BaseModel)
        mock_model_instance.model_dump_json.return_value = '{"title": "Test"}'

        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=mock_model_instance)
        mock_llm.with_structured_output.return_value = mock_structured

        extractor = StructuredExtractor(llm=mock_llm)
        result = await extractor.extract(
            text="Test content",
            schema={"type": "object", "properties": {"title": {"type": "string"}}},
        )
        parsed = json.loads(result)
        assert parsed == {"title": "Test"}

    @pytest.mark.asyncio
    async def test_strategy1_array_unwraps(self) -> None:
        mock_llm = MagicMock()
        mock_model_instance = MagicMock(spec=BaseModel)
        mock_model_instance.model_dump.return_value = {"items": [{"name": "A"}, {"name": "B"}]}

        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=mock_model_instance)
        mock_llm.with_structured_output.return_value = mock_structured

        extractor = StructuredExtractor(llm=mock_llm)
        schema = {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}}}}
        result = await extractor.extract(text="A and B", schema=schema)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "A"

    @pytest.mark.asyncio
    async def test_strategy2_fallback_object(self) -> None:
        mock_llm = MagicMock()
        mock_llm.with_structured_output.side_effect = NotImplementedError()

        mock_response = MagicMock()
        mock_response.content = '{"name": "Fallback"}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        extractor = StructuredExtractor(llm=mock_llm)
        result = await extractor.extract(
            text="Fallback content",
            schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        )
        parsed = json.loads(result)
        assert parsed["name"] == "Fallback"

    @pytest.mark.asyncio
    async def test_strategy2_fallback_array(self) -> None:
        mock_llm = MagicMock()
        mock_llm.with_structured_output.side_effect = NotImplementedError()

        mock_response = MagicMock()
        mock_response.content = '[{"name": "X"}, {"name": "Y"}]'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        extractor = StructuredExtractor(llm=mock_llm)
        schema = {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}}}}
        result = await extractor.extract(text="X and Y", schema=schema)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    @pytest.mark.asyncio
    async def test_all_strategies_fail(self) -> None:
        mock_llm = MagicMock()
        mock_llm.with_structured_output.side_effect = NotImplementedError()

        mock_response = MagicMock()
        mock_response.content = "no json whatsoever"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        extractor = StructuredExtractor(llm=mock_llm)
        result = await extractor.extract(
            text="nothing",
            schema={"type": "object", "properties": {"x": {"type": "string"}}},
        )
        assert "[Error]" in result
        assert "failed" in result

    @pytest.mark.asyncio
    async def test_already_collected_passed_to_prompt(self) -> None:
        mock_llm = MagicMock()
        mock_llm.with_structured_output.side_effect = NotImplementedError()

        mock_response = MagicMock()
        mock_response.content = '[{"name": "New"}]'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        extractor = StructuredExtractor(llm=mock_llm)
        schema = {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}}}}
        result = await extractor.extract(
            text="content",
            schema=schema,
            already_collected=[{"name": "Old"}],
        )
        parsed = json.loads(result)
        assert isinstance(parsed, list)

        call_args = mock_llm.ainvoke.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert "Already collected" in user_msg
        assert "Old" in user_msg

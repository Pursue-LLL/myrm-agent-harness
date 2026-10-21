"""Unit tests for StructuredExtractor.

Tests cover:
- Schema-to-Pydantic model conversion (object, array, nested, edge cases)
- JSON text extraction from LLM responses
- Schema complexity validation
- Full extraction flow with mocked LLM (both strategies)
- Reasoning-model content fallback (empty content → reasoning_content)
- Disabled state handling
- Error handling
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from myrm_agent_harness.toolkits.browser.session.structured_extractor import (
    StructuredExtractor,
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
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
        }
        current = schema
        for i in range(6):
            nested: dict[str, Any] = {
                "type": "object",
                "properties": {
                    f"level_{i}": {
                        "type": "object",
                        "properties": {"x": {"type": "string"}},
                    }
                },
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
        result = _extract_json_from_text('{"name": "test"}', expect_array=False)
        assert result == {"name": "test"}

    def test_direct_json_array(self) -> None:
        result = _extract_json_from_text('[{"name": "A"}, {"name": "B"}]', expect_array=True)
        assert result == [{"name": "A"}, {"name": "B"}]

    def test_empty_array(self) -> None:
        result = _extract_json_from_text("[]", expect_array=True)
        assert result == []

    def test_markdown_code_block_object(self) -> None:
        text = '```json\n{"title": "hello"}\n```'
        result = _extract_json_from_text(text, expect_array=False)
        assert result == {"title": "hello"}

    def test_markdown_code_block_array(self) -> None:
        text = '```json\n[{"a": 1}]\n```'
        result = _extract_json_from_text(text, expect_array=True)
        assert result == [{"a": 1}]

    def test_json_embedded_in_text(self) -> None:
        text = 'Here is the result: {"price": "$10"} end'
        result = _extract_json_from_text(text, expect_array=False)
        assert result == {"price": "$10"}

    def test_array_embedded_in_text(self) -> None:
        text = 'Results: [{"x": 1}] done'
        result = _extract_json_from_text(text, expect_array=True)
        assert result == [{"x": 1}]

    def test_no_json_returns_none(self) -> None:
        assert _extract_json_from_text("no json here", expect_array=False) is None

    def test_invalid_json_returns_none(self) -> None:
        assert _extract_json_from_text("{invalid json}", expect_array=False) is None

    def test_whitespace_handling(self) -> None:
        result = _extract_json_from_text('  \n  {"key": "value"}  \n  ', expect_array=False)
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
        schema = {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}}},
        }
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
            schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
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
        schema = {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}}},
        }
        result = await extractor.extract(text="X and Y", schema=schema)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    @pytest.mark.asyncio
    async def test_strategy2_reasoning_content_fallback(self) -> None:
        """Reasoning model: content empty, JSON lives in reasoning_content."""
        mock_llm = MagicMock()
        mock_llm.with_structured_output.side_effect = NotImplementedError()

        reasoning_json = '[{"name": "Reasoned"}, {"name": "Fallback"}]'
        mock_response = AIMessage(
            content="",
            additional_kwargs={"reasoning_content": reasoning_json},
        )
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        extractor = StructuredExtractor(llm=mock_llm)
        schema = {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}}},
        }
        result = await extractor.extract(text="X and Y", schema=schema)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "Reasoned"

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
        schema = {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}}},
        }
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


# --- Additional branch coverage ---


@pytest.mark.asyncio
async def test_schema_to_pydantic_failure_returns_error() -> None:
    """A schema whose property name collides with create_model kwargs fails cleanly (lines 99, 227-229)."""
    mock_llm = MagicMock()
    extractor = StructuredExtractor(llm=mock_llm)
    schema = {
        "type": "object",
        "properties": {"__base__": {"type": "string"}},
    }
    result = await extractor.extract(text="text", schema=schema)
    assert "[Error]" in result
    assert "Failed to convert" in result
    mock_llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_strategy1_generic_exception_falls_back() -> None:
    """with_structured_output throwing a generic error falls back to raw parsing (lines 124-125)."""
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.ainvoke = AsyncMock(side_effect=RuntimeError("provider down"))
    mock_llm.with_structured_output.return_value = mock_structured

    mock_response = MagicMock()
    mock_response.content = '{"name": "Survived"}'
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    extractor = StructuredExtractor(llm=mock_llm)
    result = await extractor.extract(
        text="text",
        schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    )
    parsed = json.loads(result)
    assert parsed["name"] == "Survived"
    assert mock_llm.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_strategy2_array_schema_with_dict_response() -> None:
    """Array schema with a dict response is validated and unwrapped (line 148)."""
    mock_llm = MagicMock()
    mock_llm.with_structured_output.side_effect = NotImplementedError()

    mock_response = MagicMock()
    mock_response.content = '{"items": [{"name": "A"}, {"name": "B"}]}'
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    extractor = StructuredExtractor(llm=mock_llm)
    schema = {
        "type": "array",
        "items": {"type": "object", "properties": {"name": {"type": "string"}}},
    }
    result = await extractor.extract(text="A and B", schema=schema)
    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert len(parsed) == 2


@pytest.mark.asyncio
async def test_strategy2_validation_error_returns_raw_parsed() -> None:
    """Pydantic validation failure still returns the raw parsed JSON (lines 154-159)."""
    mock_llm = MagicMock()
    mock_llm.with_structured_output.side_effect = NotImplementedError()

    mock_response = MagicMock()
    mock_response.content = '{"name": 123}'
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    extractor = StructuredExtractor(llm=mock_llm)
    result = await extractor.extract(
        text="text",
        schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    )
    parsed = json.loads(result)
    assert parsed["name"] == 123


def test_build_user_prompt_truncates_long_text() -> None:
    """_build_user_prompt truncates text beyond the 60k limit (line 181)."""
    extractor = StructuredExtractor(llm=None)
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    prompt = extractor._build_user_prompt("x" * 60001, schema, None)
    assert "[...text truncated...]" in prompt
    assert len(prompt) < 61000


def test_validate_schema_complexity_deep_array_nesting() -> None:
    """Deeply nested array-of-object schemas exceed the depth limit (line 204)."""

    def build_nested(depth: int) -> dict[str, Any]:
        leaf: dict[str, Any] = {"type": "object", "properties": {"v": {"type": "string"}}}
        for _ in range(depth):
            leaf = {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"nested": leaf},
                },
            }
        return {"type": "object", "properties": {"root": leaf}}

    assert _validate_schema_complexity(build_nested(3)) is True
    assert _validate_schema_complexity(build_nested(8)) is False


def test_extract_json_invalid_markdown_block_returns_none() -> None:
    """A code block containing invalid JSON yields None without raising (lines 300-301)."""
    text = "```json\n{invalid json here}\n```"
    assert _extract_json_from_text(text, expect_array=False) is None


@pytest.mark.asyncio
async def test_strategy2_generic_exception_returns_error() -> None:
    """A non-validation error during fallback extraction yields the final error (lines 158-159)."""
    mock_llm = MagicMock()
    mock_llm.with_structured_output.side_effect = NotImplementedError()
    mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("fallback crashed"))

    extractor = StructuredExtractor(llm=mock_llm)
    result = await extractor.extract(
        text="text",
        schema={"type": "object", "properties": {"x": {"type": "string"}}},
    )
    assert "[Error]" in result
    assert "failed" in result

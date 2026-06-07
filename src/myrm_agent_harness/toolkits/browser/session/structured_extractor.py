"""Structured content extractor using LLM with JSON Schema validation.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LLM instance for structured extraction)
- str (POS: raw page text to extract from)
- dict (POS: JSON Schema defining desired output structure)

[OUTPUT]
- StructuredExtractor: Component that extracts structured data from raw text using LLM.

[POS]
Extracts structured data from raw page text by:
1. Validating the provided JSON Schema
2. Converting JSON Schema to a Pydantic model dynamically
3. Invoking LLM with `with_structured_output` for guaranteed schema compliance
4. Falling back to raw JSON parsing if structured output is unavailable
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any  # Any: required for JSON Schema (inherently dynamic dict values)

from pydantic import BaseModel, ValidationError, create_model
from pydantic.fields import FieldInfo

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

_MAX_SCHEMA_PROPERTIES = 50
_MAX_SCHEMA_DEPTH = 5

_EXTRACTION_SYSTEM_PROMPT = (
    "You are a precise data extraction engine. "
    "Given the raw text from a web page, extract data that matches the provided JSON Schema. "
    "Output ONLY a valid JSON object conforming to the schema. "
    "If a field cannot be found in the text, use null. "
    "Do not add extra fields. Do not wrap in markdown code blocks."
)


class StructuredExtractor:
    """Extracts structured data from page text using LLM + JSON Schema."""

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        """Initialize StructuredExtractor.

        Args:
            llm: LLM instance capable of structured output. If None, extraction is disabled.
        """
        self._llm = llm

    @property
    def enabled(self) -> bool:
        """Whether structured extraction is available."""
        return self._llm is not None

    async def extract(
        self,
        text: str,
        schema: dict[str, Any],
        *,
        already_collected: list[dict[str, Any]] | None = None,
    ) -> str:
        """Extract structured data from text according to schema.

        Args:
            text: Raw page text to extract from.
            schema: JSON Schema dict defining the desired output structure.
            already_collected: Previously collected items to avoid duplicates.

        Returns:
            JSON string of extracted data conforming to schema,
            or error message if extraction fails.
        """
        if self._llm is None:
            return '[Error] Structured extraction unavailable: no extraction LLM configured.'

        if not _validate_schema_complexity(schema):
            return (
                f'[Error] Schema too complex (max {_MAX_SCHEMA_PROPERTIES} properties, '
                f'max {_MAX_SCHEMA_DEPTH} nesting levels).'
            )

        is_array_schema = schema.get("type") == "array"
        pydantic_model = _schema_to_pydantic(schema)
        if pydantic_model is None:
            return '[Error] Failed to convert JSON Schema to extraction model.'

        user_content = self._build_user_prompt(text, schema, already_collected)

        # Strategy 1: with_structured_output (preferred)
        try:
            structured_llm = self._llm.with_structured_output(pydantic_model)
            result = await structured_llm.ainvoke(
                [
                    {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ]
            )
            if isinstance(result, BaseModel):
                if is_array_schema:
                    return json.dumps(
                        result.model_dump().get("items", []), ensure_ascii=False, indent=2
                    )
                return result.model_dump_json(indent=2)
        except (NotImplementedError, AttributeError):
            logger.debug("StructuredExtractor: with_structured_output not supported, using fallback.")
        except Exception as e:
            logger.warning("StructuredExtractor: structured output failed (%s), trying fallback.", e)

        # Strategy 2: Raw JSON extraction from LLM response
        parsed: dict[str, Any] | list[dict[str, Any]] | None = None
        try:
            raw_response = await self._llm.ainvoke(
                [
                    {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ]
            )
            content = str(raw_response.content)
            parsed = _extract_json_from_text(content)
            if parsed is not None:
                if is_array_schema and isinstance(parsed, list):
                    return json.dumps(parsed, ensure_ascii=False, indent=2)
                if isinstance(parsed, dict):
                    validated = pydantic_model.model_validate(parsed)
                    if is_array_schema:
                        return json.dumps(
                            validated.model_dump().get("items", []), ensure_ascii=False, indent=2
                        )
                    return validated.model_dump_json(indent=2)
        except ValidationError as ve:
            logger.warning("StructuredExtractor: validation failed: %s", ve)
            if parsed is not None:
                return json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("StructuredExtractor: fallback extraction failed: %s", e)

        return '[Error] Structured extraction failed after all attempts.'

    def _build_user_prompt(
        self,
        text: str,
        schema: dict[str, Any],
        already_collected: list[dict[str, Any]] | None,
    ) -> str:
        """Build the user prompt for extraction."""
        parts = [
            f"JSON Schema to extract:\n```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```\n",
        ]
        if already_collected:
            parts.append(
                f"Already collected items (skip duplicates):\n"
                f"```json\n{json.dumps(already_collected, ensure_ascii=False)}\n```\n"
            )
        # Truncate text to avoid exceeding LLM context limits
        max_text_len = 60000
        if len(text) > max_text_len:
            text = text[:max_text_len] + "\n\n[...text truncated...]"
        parts.append(f"Web page text:\n---\n{text}\n---")
        return "\n".join(parts)


def _validate_schema_complexity(schema: dict[str, Any], depth: int = 0) -> bool:
    """Validate schema doesn't exceed complexity limits."""
    if depth > _MAX_SCHEMA_DEPTH:
        return False

    properties = schema.get("properties", {})
    if len(properties) > _MAX_SCHEMA_PROPERTIES:
        return False

    for _key, prop in properties.items():
        if prop.get("type") == "object":
            if not _validate_schema_complexity(prop, depth + 1):
                return False
        elif prop.get("type") == "array":
            items = prop.get("items", {})
            if items.get("type") == "object":
                if not _validate_schema_complexity(items, depth + 1):
                    return False

    return True


def _schema_to_pydantic(schema: dict[str, Any]) -> type[BaseModel] | None:
    """Convert a JSON Schema dict to a dynamic Pydantic model.

    Supports: object, array, string, number, integer, boolean, null.
    Nested objects become nested Pydantic models.
    Top-level array schemas are wrapped as an object with an 'items' list field.
    """
    try:
        if schema.get("type") == "array":
            return _build_model("ExtractedData", {
                "type": "object",
                "properties": {"items": schema},
                "required": ["items"],
            })
        return _build_model("ExtractedData", schema)
    except Exception as e:
        logger.error("Failed to build Pydantic model from schema: %s", e)
        return None


def _build_model(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """Recursively build a Pydantic model from JSON Schema."""
    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))
    field_definitions: dict[str, Any] = {}

    for field_name, field_schema in properties.items():
        python_type = _json_type_to_python(field_name, field_schema)
        description = field_schema.get("description", "")
        is_required = field_name in required_fields

        if is_required:
            field_definitions[field_name] = (python_type, FieldInfo(description=description))
        else:
            field_definitions[field_name] = (python_type | None, FieldInfo(default=None, description=description))

    return create_model(name, **field_definitions)  # type: ignore[call-overload]


def _json_type_to_python(field_name: str, field_schema: dict[str, Any]) -> type:
    """Map JSON Schema type to Python type."""
    json_type = field_schema.get("type", "string")

    if json_type == "string":
        return str
    elif json_type == "number":
        return float
    elif json_type == "integer":
        return int
    elif json_type == "boolean":
        return bool
    elif json_type == "array":
        items_schema = field_schema.get("items", {})
        if items_schema.get("type") == "object":
            item_model = _build_model(f"{field_name}_Item", items_schema)
            return list[item_model]  # type: ignore[valid-type]
        item_type = _json_type_to_python(f"{field_name}_item", items_schema)
        return list[item_type]  # type: ignore[valid-type]
    elif json_type == "object":
        return _build_model(field_name.capitalize(), field_schema)
    else:
        return str


def _extract_json_from_text(text: str) -> dict[str, Any] | list[Any] | None:
    """Extract JSON object or array from LLM response text."""
    text = text.strip()

    # Try direct parse (object or array)
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Try to find JSON in markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find any JSON object or array
    for pattern in (r"\[.*\]", r"\{.*\}"):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    return None

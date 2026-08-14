"""MCP Schema-Driven Argument Coercion.

Normalizes LLM-emitted tool arguments against the tool's JSON Schema before
dispatch: type coercion (string "100" → int, "true" → bool, container
literals → object/array), arbitrary-precision numeric preservation (exact
Decimal parsing keeps big integers and whole-valued exponent/float-form
literals lossless, bounded by int_max_str_digits; non-finite literals stay
strings), bare-scalar → single-element array wrapping for ``array`` schemas,
numeric 1/0 ↔ boolean bidirectional coercion, a 64KB length guard on
container-literal parsing (degenerate-output CPU/memory defense), strict-host
nullable completion (missing required+nullable fields → explicit ``None``),
and stripping of null optional fields that strict MCP servers reject.

[INPUT]
- args_schema dict (from ``StructuredTool.args_schema``)
- kwargs emitted by the LLM

[OUTPUT]
- coerce_arguments_by_schema: Corrects parsed arguments, handles mixed-union container literals, and completes required nullable omissions.
- prepare_mcp_call_arguments: Strip null optional fields before MCP call_tool (strict JSON Schema hosts).
- get_schema_coercion_stats/reset_schema_coercion_stats: Lightweight runtime coercion counters.

[POS]
MCP Schema Utilities. Dynamic type coercion, strict-host nullable
completion, mixed-union safe container coercion, and coercion
observability counters.
"""

import ast
import json
import logging
import math
import re
import sys
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

# Strings longer than this are never parsed as JSON/AST container literals.
# A degenerate LLM output (multi-hundred-KB "object") would otherwise burn
# CPU on json.loads/ast.literal_eval for nothing. Mirrors openclaw's
# MAX_JSON_COERCE_LENGTH (64 * 1024).
_MAX_JSON_COERCE_LENGTH = 64 * 1024

_SCHEMA_COERCION_STAT_KEYS = (
    "coerce_argument_calls",
    "null_string_to_none",
    "required_nullable_null_injections",
    "json_container_coercions",
    "json_type_guard_rejections",
    "ast_container_coercions",
    "ast_type_guard_rejections",
    "scalar_to_array_wraps",
    "bool_number_cross_coercions",
)
_SCHEMA_COERCION_STATS: dict[str, int] = {key: 0 for key in _SCHEMA_COERCION_STAT_KEYS}


def _bump_schema_coercion_stat(key: str) -> None:
    if key in _SCHEMA_COERCION_STATS:
        _SCHEMA_COERCION_STATS[key] += 1


def get_schema_coercion_stats() -> dict[str, int]:
    """Return a snapshot of best-effort schema coercion counters."""
    return dict(_SCHEMA_COERCION_STATS)


def reset_schema_coercion_stats() -> None:
    """Reset schema coercion counters (useful for deterministic tests)."""
    for key in _SCHEMA_COERCION_STATS:
        _SCHEMA_COERCION_STATS[key] = 0


def _strip_markdown_json(value: str) -> str:
    """Safely strip markdown code block backticks if present."""
    value = value.strip()
    if value.startswith("```"):
        # Match ```json\n ... \n``` or just ``` ... ```
        match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", value, re.DOTALL)
        if match:
            return match.group(1).strip()
    return value


def _looks_like_json_container_literal(value: str) -> bool:
    """Heuristic: looks like a JSON object/array literal."""
    stripped = value.strip()
    if len(stripped) < 2:
        return False
    return (stripped[0] == "{" and stripped[-1] == "}") or (stripped[0] == "[" and stripped[-1] == "]")


def _extract_schema_types(schema: dict[str, Any]) -> list[str]:
    """Collect declared JSON schema types from direct and union forms."""
    collected: list[str] = []

    def _append_types(raw_type: Any) -> None:
        if isinstance(raw_type, str):
            if raw_type not in collected:
                collected.append(raw_type)
            return
        if isinstance(raw_type, list):
            for item in raw_type:
                if isinstance(item, str) and item not in collected:
                    collected.append(item)

    _append_types(schema.get("type"))
    for union_key in ("anyOf", "oneOf"):
        variants = schema.get(union_key)
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if isinstance(variant, dict):
                _append_types(variant.get("type"))

    return collected


def _schema_declares_null_literal(schema: dict[str, Any]) -> bool:
    """Return True when a single schema node explicitly allows a null literal."""
    if schema.get("nullable") is True:
        return True
    if "const" in schema and schema["const"] is None:
        return True
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and any(item is None for item in enum_values):
        return True
    return "null" in _extract_schema_types(schema)


def _schema_allows_null(schema: dict[str, Any]) -> bool:
    """Return True when the schema explicitly permits null."""
    if _schema_declares_null_literal(schema):
        return True
    for union_key in ("anyOf", "oneOf"):
        variants = schema.get(union_key)
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if isinstance(variant, dict) and _schema_declares_null_literal(variant):
                return True
    return False


def prepare_mcp_call_arguments(
    kwargs: dict[str, object],
    args_schema: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Prepare kwargs for MCP ``call_tool``.

    StructuredTool/Pydantic validation may expand omitted optional fields to
    explicit ``None``. Strict MCP servers (e.g. 12306) reject ``null`` for
    typed optional properties that define non-null defaults — those keys must
    be omitted instead.

    Preserves explicit ``None`` only for required properties whose schema
    allows null (strict-host nullable completion from coercion).
    """
    if not kwargs:
        return kwargs

    properties: dict[str, Any] = {}
    required: set[str] = set()
    if isinstance(args_schema, dict):
        raw_props = args_schema.get("properties")
        if isinstance(raw_props, dict):
            properties = raw_props
        raw_required = args_schema.get("required")
        if isinstance(raw_required, list):
            required = {key for key in raw_required if isinstance(key, str)}

    prepared: dict[str, object] = {}
    for key, value in kwargs.items():
        if value is not None:
            prepared[key] = value
            continue
        prop_schema = properties.get(key)
        if key in required and isinstance(prop_schema, dict) and _schema_allows_null(prop_schema):
            prepared[key] = None
    return prepared


def _primary_non_null_type(schema: dict[str, Any]) -> str | None:
    """Pick the first non-null declared type for coercion decisions."""
    for schema_type in _extract_schema_types(schema):
        if schema_type != "null":
            return schema_type
    return None


def _schema_expects_type(schema: dict[str, Any], expected_type: str) -> bool:
    """Return True when schema accepts the given type."""
    return expected_type in _extract_schema_types(schema)


def _value_conforms_to_schema_types(schema: dict[str, Any], value: Any) -> bool:
    """Return True when runtime value already matches one allowed schema type."""
    if value is None:
        return _schema_allows_null(schema)
    if isinstance(value, bool):
        return _schema_expects_type(schema, "boolean")
    if isinstance(value, dict):
        return _schema_expects_type(schema, "object")
    if isinstance(value, list):
        return _schema_expects_type(schema, "array")
    if isinstance(value, int):
        return _schema_expects_type(schema, "integer") or _schema_expects_type(schema, "number")
    if isinstance(value, float):
        return _schema_expects_type(schema, "number")
    if isinstance(value, str):
        return _schema_expects_type(schema, "string")
    return False


def coerce_value(schema: dict[str, Any], value: Any) -> Any:
    """Recursively coerces a value based on the JSON schema definition."""
    if not isinstance(schema, dict):
        return value

    expected_type = _primary_non_null_type(schema)
    allows_null = _schema_allows_null(schema)

    # If we got a string but expected something else (LLM hallucination)
    if isinstance(value, str):
        clean_value = _strip_markdown_json(value)

        if allows_null and clean_value.lower() == "null":
            _bump_schema_coercion_stat("null_string_to_none")
            return None

        expects_object = _schema_expects_type(schema, "object")
        expects_array = _schema_expects_type(schema, "array")
        should_attempt_container_parse = False
        if expects_object or expects_array:
            should_attempt_container_parse = expected_type in (
                "array",
                "object",
            ) or _looks_like_json_container_literal(clean_value)

        if should_attempt_container_parse and len(clean_value) <= _MAX_JSON_COERCE_LENGTH:
            try:
                coerced_value = json.loads(clean_value)
                if expects_array and isinstance(coerced_value, list):
                    value = coerced_value
                    _bump_schema_coercion_stat("json_container_coercions")
                    logger.debug("Coerced from string to list via JSON")
                elif expects_object and isinstance(coerced_value, dict):
                    value = coerced_value
                    _bump_schema_coercion_stat("json_container_coercions")
                    logger.debug("Coerced from string to dict via JSON")
                else:
                    _bump_schema_coercion_stat("json_type_guard_rejections")
                    logger.debug(
                        "Rejected JSON coercion for schema (expects object=%s array=%s): got %s",
                        expects_object,
                        expects_array,
                        type(coerced_value).__name__,
                    )
            except json.JSONDecodeError:
                try:
                    coerced_value = ast.literal_eval(clean_value)
                    if expects_array and isinstance(coerced_value, list):
                        value = coerced_value
                        _bump_schema_coercion_stat("ast_container_coercions")
                        logger.debug("Coerced from string to list via AST")
                    elif expects_object and isinstance(coerced_value, dict):
                        value = coerced_value
                        _bump_schema_coercion_stat("ast_container_coercions")
                        logger.debug("Coerced from string to dict via AST")
                    else:
                        _bump_schema_coercion_stat("ast_type_guard_rejections")
                        logger.debug(
                            "Rejected AST coercion for schema (expects object=%s array=%s): got %s",
                            expects_object,
                            expects_array,
                            type(coerced_value).__name__,
                        )
                except (ValueError, SyntaxError):
                    pass
        elif expected_type == "boolean":
            lower_val = clean_value.lower()
            if lower_val == "true":
                value = True
            elif lower_val == "false":
                value = False
        elif expected_type in ("integer", "number"):
            try:
                is_pure_int = not any(ch in clean_value for ch in ".eE")
                if is_pure_int:
                    # Pure integer literal: int() preserves arbitrary precision
                    # (Python ints are unbounded). Python's built-in
                    # int_max_str_digits guard (4300 digits) rejects absurdly
                    # long literals with ValueError, which we swallow below.
                    value = int(clean_value)
                else:
                    # Decimal/exponent form: parse exactly with Decimal and
                    # keep an exact integer when the literal denotes one
                    # (e.g. "25.0", "1e3", "9007199254740993.0" — int() would
                    # reject the first two and float() would silently lose
                    # precision on the last).  Non-integral values under a
                    # "number" expectation still fall through to float().
                    try:
                        decimal_value = Decimal(clean_value)
                    except InvalidOperation:
                        decimal_value = None
                    if decimal_value is not None and decimal_value == decimal_value.to_integral_value():
                        # int(Decimal) bypasses the int_max_str_digits string
                        # guard, so enforce the same limit ourselves to avoid
                        # materializing a gigantic int (memory DoS).
                        if decimal_value.adjusted() + 1 > sys.get_int_max_str_digits():
                            raise ValueError(f"{clean_value!r} exceeds int digit limit")
                        value = int(decimal_value)
                    elif expected_type == "number":
                        value = float(clean_value)
                        if not math.isfinite(value):
                            # "inf" / "-inf" / "nan" are not valid JSON numbers
                            # — keep the string (mirrors openclaw's
                            # Number.isFinite guard).
                            value = clean_value
                    else:
                        # "integer" expectation with a genuinely fractional
                        # literal: keep the string (mirrors openclaw's
                        # Number.isInteger check which rejects non-integers).
                        raise ValueError(f"{clean_value!r} is not an integer")
            except ValueError:
                pass

    # Reverse: got a non-string but expected string (e.g. LLM passed dict for station name)
    if expected_type == "string" and not isinstance(value, str) and not _value_conforms_to_schema_types(schema, value):
        if isinstance(value, dict):
            for text_key in ("name", "value", "text", "id"):
                if text_key in value and isinstance(value[text_key], str):
                    logger.debug("Coerced dict to string via key '%s'", text_key)
                    value = value[text_key]
                    break
            else:
                value = json.dumps(value, ensure_ascii=False)
                logger.debug("Coerced dict to string via JSON serialization")
        elif isinstance(value, (int, float, bool)):
            value = str(value)
        elif isinstance(value, list):
            value = json.dumps(value, ensure_ascii=False)

    # Bare scalar → single-element array when the schema expects an array.
    # Open-weight models (DeepSeek, Qwen, GLM) often emit a bare scalar where
    # a list is required (e.g. {"urls": "https://a.com"} for urls: array).
    # Wrapping repairs the call instead of failing it; skip when the value is
    # already a list or when the schema already accepts its current type.
    # Mirrors hermes-agent's coerce_tool_args wrapping (with its warning when
    # a JSON-array-looking string could not be parsed).
    if (
        expected_type == "array"
        and value is not None
        and not isinstance(value, (list, tuple))
        and not _value_conforms_to_schema_types(schema, value)
    ):
        wrapped_value = _strip_markdown_json(value) if isinstance(value, str) else value
        looks_like_container = isinstance(wrapped_value, str) and wrapped_value.strip().startswith(("[", "{"))
        length_guarded = isinstance(wrapped_value, str) and len(wrapped_value.strip()) > _MAX_JSON_COERCE_LENGTH
        if not (looks_like_container and length_guarded):
            if looks_like_container:
                logger.warning(
                    "coerce_value: value %r looks like a JSON array string but could "
                    "not be parsed — wrapping into a single-element list",
                    wrapped_value,
                )
            value = [wrapped_value]
            _bump_schema_coercion_stat("scalar_to_array_wraps")

    # Numeric 1/0 ↔ boolean bidirectional coercion. LLMs sometimes emit 1/0
    # for a boolean field (or True/False for a number field) — convert only
    # when the current type is not already accepted by the schema.
    # Mirrors openclaw validation.ts coercePrimitiveByType (which treats any
    # number — including float forms like 1.0/0.0 — as a boolean candidate).
    if expected_type == "boolean" and not _value_conforms_to_schema_types(schema, value):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value in (0, 1):
            value = bool(value)
            _bump_schema_coercion_stat("bool_number_cross_coercions")
    elif expected_type in ("integer", "number") and not _value_conforms_to_schema_types(schema, value):
        if isinstance(value, bool):
            value = int(value)
            _bump_schema_coercion_stat("bool_number_cross_coercions")

    # Recursive descent for objects
    if _schema_expects_type(schema, "object") and isinstance(value, dict):
        properties = schema.get("properties", {})
        coerced_dict = {}
        for k, v in value.items():
            if k in properties:
                coerced_dict[k] = coerce_value(properties[k], v)
            else:
                coerced_dict[k] = v
        return coerced_dict

    # Recursive descent for arrays
    if _schema_expects_type(schema, "array") and isinstance(value, list):
        items_schema = schema.get("items", {})
        if items_schema:
            return [coerce_value(items_schema, item) for item in value]

    return value


def coerce_arguments_by_schema(args_schema: dict[str, Any] | None, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Coerces argument types based on the schema requirements.

    If the schema expects an array, object, boolean, or number, but the LLM
    provided a string, this attempts to safely parse the string into the
    expected type. Also strips markdown code blocks. Bare scalars for ``array``
    schemas wrap into a single-element list; int 0/1 ↔ boolean coercions are
    applied when the current type isn't already accepted by the schema.
    Recursively descends into objects and arrays to heal nested hallucinations.
    For strict hosts, fills missing required fields with explicit ``None`` only
    when the corresponding property schema allows ``null``.
    """
    if not args_schema or not isinstance(args_schema, dict):
        return kwargs

    _bump_schema_coercion_stat("coerce_argument_calls")

    properties = args_schema.get("properties", {})
    if not properties:
        return kwargs

    coerced_kwargs = {}
    for key, value in kwargs.items():
        if key in properties:
            coerced_kwargs[key] = coerce_value(properties[key], value)
        else:
            coerced_kwargs[key] = value

    required_keys = args_schema.get("required", [])
    if isinstance(required_keys, list):
        for required_key in required_keys:
            if not isinstance(required_key, str) or required_key in coerced_kwargs:
                continue
            prop_schema = properties.get(required_key)
            if isinstance(prop_schema, dict) and _schema_allows_null(prop_schema):
                # Strict hosts (e.g. Unreal MCP) may require explicit null
                # for missing required+nullable optional fields.
                coerced_kwargs[required_key] = None
                _bump_schema_coercion_stat("required_nullable_null_injections")

    return coerced_kwargs

"""LiteLLM utility functions


[INPUT]
- dataclasses::dataclass (POS: recovery result data structure)
- json::json (POS: Python JSON library)
- re::re (POS: Python regex library)
- utils.truncated_json::close_truncated_json, ends_inside_string (POS: cut-off JSON completion primitives)

[OUTPUT]
- ToolArgumentRecoveryResult: tool argument recovery result
- fix_invalid_json_escapes(): fix invalid JSON escape sequences
- extract_json_from_malformed_response(): extract JSON from malformed responses
- parse_tool_call_arguments_with_recovery(): unified schema-aware tool argument fault-tolerant recovery

[POS]
LiteLLM utility functions. Provides JSON processing tools for handling LLM-generated malformed JSON.
Fixes invalid escapes, extracts pure JSON content, and performs schema-aware fault-tolerant parsing.
Model-parameter sanitization (`clean_model_kwargs`) lives in ``model_kwargs.py``.
As the utility layer, depended on by adapters.converters and adapters.tool_recovery.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from myrm_agent_harness.toolkits.llms.utils.truncated_json import close_truncated_json, ends_inside_string

logger = logging.getLogger(__name__)

_COMMON_ARTIFACT_PATTERNS = (
    r"\]\s*<\|FunctionCallEnd\|>.*$",
    r"<\|FunctionCallEnd\|>.*$",
)
_HIGH_RISK_LONG_TEXT_FIELDS = (
    "content",
    "text",
    "query",
    "command",
    "code",
    "body",
    "prompt",
    "file_text",
    "sql",
    "script",
)
_PERMISSION_CRITICAL_FIELDS = frozenset({"command", "path", "file_path", "url", "cwd", "base_path"})


@dataclass(frozen=True, slots=True)
class ToolArgumentRecoveryResult:
    """Unified recovery result for tool call arguments."""

    args: dict[str, object]
    strategy: str
    degraded: bool = False
    safe: bool = True


def fix_invalid_json_escapes(json_str: str) -> str:
    """Fix invalid escape sequences in JSON string.

    Some LLMs generate code with invalid escape sequences like \\' which is not valid in JSON.
    This function converts such invalid escapes to valid alternatives.

    Args:
        json_str: The JSON string to fix

    Returns:
        Fixed JSON string with valid escape sequences
    """
    # Replace \\' with a placeholder first
    placeholder = "\x00ESCAPED_BACKSLASH_QUOTE\x00"
    result = json_str.replace("\\\\'", placeholder)
    # Now replace \' with just '
    result = result.replace("\\'", "'")
    # Restore the placeholder
    result = result.replace(placeholder, "\\\\'")

    return result


def _strip_common_artifacts(text: str) -> str:
    result = text.strip()
    for pattern in _COMMON_ARTIFACT_PATTERNS:
        result = re.sub(pattern, "", result, flags=re.DOTALL)
    return result.strip()


def _load_json_object(text: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _resolve_parameters_schema(tool_schema: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not tool_schema:
        return None

    if isinstance(tool_schema.get("function"), Mapping):
        function_obj = tool_schema["function"]
        params = function_obj.get("parameters")
        return params if isinstance(params, Mapping) else None

    params = tool_schema.get("parameters")
    return params if isinstance(params, Mapping) else None


def _iter_string_field_candidates(
    text: str,
    tool_schema: Mapping[str, Any] | None,
) -> list[str]:
    params = _resolve_parameters_schema(tool_schema)
    properties = params.get("properties") if isinstance(params, Mapping) else None
    schema_fields: list[str] = []
    if isinstance(properties, Mapping):
        for field_name, field_schema in properties.items():
            if not isinstance(field_name, str) or not isinstance(field_schema, Mapping):
                continue
            field_type = field_schema.get("type")
            is_string = field_type == "string" or (
                isinstance(field_type, list) and any(item == "string" for item in field_type)
            )
            if is_string:
                schema_fields.append(field_name)

    present_fields = [name for name in schema_fields if f'"{name}"' in text]
    prioritized = [name for name in _HIGH_RISK_LONG_TEXT_FIELDS if name in present_fields]
    remaining = [name for name in present_fields if name not in prioritized]

    if prioritized or remaining:
        return prioritized + remaining

    return [name for name in _HIGH_RISK_LONG_TEXT_FIELDS if f'"{name}"' in text]


def _repair_string_field_value(text: str, field_name: str) -> str | None:
    match = re.search(rf'"{re.escape(field_name)}"\s*:\s*"', text)
    if match is None:
        return None

    start = match.end()
    repaired: list[str] = []
    end_index: int | None = None
    i = start

    while i < len(text):
        char = text[i]
        if char == '"':
            j = i + 1
            while j < len(text) and text[j].isspace():
                j += 1
            if j >= len(text) or text[j] in {",", "}", "]"}:
                end_index = i
                break
            repaired.append('\\"')
            i += 1
            continue
        if char == "\n":
            repaired.append("\\n")
        elif char == "\r":
            repaired.append("\\r")
        elif char == "\t":
            repaired.append("\\t")
        else:
            repaired.append(char)
        i += 1

    if end_index is None:
        return None

    return f"{text[:start]}{''.join(repaired)}{text[end_index:]}"


_NONE_OUTSIDE_STRINGS = re.compile(r'("(?:\\.?|[^"\\])*(?:"|\Z))|\bNone\b', re.DOTALL)


def _decode_string_value(raw_value: str) -> str:
    return (
        raw_value.replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )


def _regex_fallback_extract(
    text: str,
    tool_schema: Mapping[str, Any] | None,
) -> dict[str, object]:
    params = _resolve_parameters_schema(tool_schema)
    properties = params.get("properties") if isinstance(params, Mapping) else None
    candidate_fields: list[str]
    if isinstance(properties, Mapping) and properties:
        candidate_fields = [name for name in properties if isinstance(name, str)]
    else:
        candidate_fields = [*list(_HIGH_RISK_LONG_TEXT_FIELDS), "path", "file_path", "url"]

    extracted: dict[str, object] = {}
    for field_name in candidate_fields:
        if field_name in extracted:
            continue

        strict_string_match = re.search(
            rf'"{re.escape(field_name)}"\s*:\s*"((?:\\.|[^"\\])*)"',
            text,
            flags=re.DOTALL,
        )
        if strict_string_match is not None:
            value = _decode_string_value(strict_string_match.group(1).strip())
            if value:
                extracted[field_name] = value
                continue

        string_match = re.search(rf'"{re.escape(field_name)}"\s*:\s*"', text)
        if string_match is not None:
            start = string_match.end()
            buffer: list[str] = []
            i = start
            while i < len(text):
                char = text[i]
                if char == "\\" and i + 1 < len(text):
                    buffer.append(char)
                    buffer.append(text[i + 1])
                    i += 2
                    continue
                if char == '"':
                    j = i + 1
                    while j < len(text) and text[j].isspace():
                        j += 1
                    if j >= len(text) or text[j] in {",", "}", "]"}:
                        break
                buffer.append(char)
                i += 1

            value = _decode_string_value("".join(buffer).strip())
            if value:
                extracted[field_name] = value
                continue

        scalar_match = re.search(
            rf'"{re.escape(field_name)}"\s*:\s*(true|false|null|-?\d+(?:\.\d+)?)',
            text,
            flags=re.IGNORECASE,
        )
        if scalar_match is None:
            continue

        raw_scalar = scalar_match.group(1)
        if raw_scalar.lower() == "true":
            extracted[field_name] = True
        elif raw_scalar.lower() == "false":
            extracted[field_name] = False
        elif raw_scalar.lower() == "null":
            extracted[field_name] = None
        elif "." in raw_scalar:
            extracted[field_name] = float(raw_scalar)
        else:
            extracted[field_name] = int(raw_scalar)

    return extracted


def _is_safe_degraded_result(
    recovered_args: Mapping[str, object],
    tool_schema: Mapping[str, Any] | None,
) -> bool:
    if not recovered_args:
        return False

    params = _resolve_parameters_schema(tool_schema)
    if not params:
        return not any(key in _PERMISSION_CRITICAL_FIELDS for key in recovered_args)

    required_obj = params.get("required", [])
    required = [item for item in required_obj if isinstance(item, str)] if isinstance(required_obj, list) else []
    return all(field in recovered_args for field in required)


def _refuse_cut_off_value(tool_name: str) -> ToolArgumentRecoveryResult:
    """Refuse to close a string value that was cut open.

    A closed prefix of a path, command or file body parses as a valid, shorter value
    that is indistinguishable from the intended one — and a provider can report a
    normal finish for a stream it cut short, so ``stream_complete`` alone cannot be
    trusted to catch it.
    """
    logger.warning(" Tool args cut off inside a string value for %s — refusing repair", tool_name)
    return ToolArgumentRecoveryResult(args={}, strategy="truncated_mid_value", degraded=True, safe=False)


def parse_tool_call_arguments_with_recovery(
    args: str | dict[str, object],
    tool_name: str,
    tool_schema: Mapping[str, Any] | None = None,
    *,
    stream_complete: bool | None = None,
) -> ToolArgumentRecoveryResult:
    """Recover malformed tool-call argument JSON using a strict staged pipeline.

    Supports 8 recovery strategies, tried in this order:
    1. Standard JSON parsing (valid input is returned untouched)
    2. Python None → JSON null (bare tokens only; "None" inside a string is data)
    3. Invalid escape sequence fixing
    4. Long text field repair (schema-aware)
    5. Truncated JSON completion (refused as unsafe when the text ends inside a
       string value: a cut-open string cannot be told apart from a finished one)
    6. Malformed JSON extraction
    7. Excess closing delimiter removal (Weak model outputs excess} or ])
    8. Regex fallback (marked as unsafe)

    Args:
        args: Raw argument payload (JSON string or already-decoded dict).
        tool_name: Tool name, for logging and schema resolution.
        tool_schema: Optional OpenAI tool schema used by schema-aware repairs.
        stream_complete: Whether the producing stream ended normally. ``False``
            means the provider stopped mid-generation (missing ``finish_reason``
            or ``length``/``max_tokens``) and the argument text is known to be
            incomplete; in that case every repair that would *close* the partial
            JSON is refused, because a closed prefix parses as a valid object
            that silently lacks every field not yet streamed. ``None`` means the
            caller cannot tell (non-streaming, direct invocation) and the staged
            pipeline runs unchanged.
    """
    if isinstance(args, dict):
        return ToolArgumentRecoveryResult(args=args, strategy="dict_input")

    normalized = _strip_common_artifacts(args)

    parsed = _load_json_object(normalized)
    if parsed is not None:
        return ToolArgumentRecoveryResult(args=parsed, strategy="standard_json")

    # Python None → JSON null, outside string literals only ("None" inside a string value is user data).
    python_to_json = _NONE_OUTSIDE_STRINGS.sub(lambda m: m.group(1) or "null", normalized)
    if python_to_json != normalized:
        parsed = _load_json_object(python_to_json)
        if parsed is not None:
            return ToolArgumentRecoveryResult(args=parsed, strategy="python_none_to_null", degraded=True)
        normalized = python_to_json

    if stream_complete is False:
        # A truncated stream cannot be safely repaired: closing the partial JSON
        # fabricates a syntactically valid object missing every field that had
        # not streamed yet. Refuse rather than execute a silently-wrong call.
        logger.warning(" Tool args stream truncated for %s — refusing repair", tool_name)
        return ToolArgumentRecoveryResult(
            args={},
            strategy="truncated_stream_unverified",
            degraded=True,
            safe=False,
        )

    escaped = fix_invalid_json_escapes(normalized)
    if escaped != normalized:
        parsed = _load_json_object(escaped)
        if parsed is not None:
            return ToolArgumentRecoveryResult(args=parsed, strategy="fixed_invalid_escapes")

    long_text_candidates = _iter_string_field_candidates(escaped, tool_schema)
    for field_name in long_text_candidates:
        repaired = _repair_string_field_value(escaped, field_name)
        if repaired is None:
            continue
        parsed = _load_json_object(repaired)
        if parsed is not None:
            return ToolArgumentRecoveryResult(
                args=parsed,
                strategy=f"long_text_field_repair:{field_name}",
            )

        truncated_repaired = close_truncated_json(repaired)
        parsed = _load_json_object(truncated_repaired)
        if parsed is not None:
            if ends_inside_string(repaired):
                return _refuse_cut_off_value(tool_name)
            return ToolArgumentRecoveryResult(
                args=parsed,
                strategy=f"long_text_then_truncated_completion:{field_name}",
            )

    truncated = close_truncated_json(escaped)
    if truncated != escaped:
        parsed = _load_json_object(truncated)
        if parsed is not None:
            if ends_inside_string(escaped):
                return _refuse_cut_off_value(tool_name)
            return ToolArgumentRecoveryResult(args=parsed, strategy="truncated_completion")

    try:
        parsed = extract_json_from_malformed_response(escaped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return ToolArgumentRecoveryResult(args=parsed, strategy="malformed_json_extraction")

    # Strategy: Remove excess closing braces/brackets
    fixed = escaped
    for _ in range(50):
        try:
            parsed = json.loads(fixed)
            if isinstance(parsed, dict):
                return ToolArgumentRecoveryResult(
                    args=parsed,
                    strategy="remove_excess_closing",
                    degraded=True,
                )
        except json.JSONDecodeError:
            # Try removing excess closing delimiter
            if (fixed.endswith("}") and fixed.count("}") > fixed.count("{")) or (
                fixed.endswith("]") and fixed.count("]") > fixed.count("[")
            ):
                fixed = fixed[:-1]
            else:
                break

    fallback = _regex_fallback_extract(escaped, tool_schema)
    if fallback:
        safe = _is_safe_degraded_result(fallback, tool_schema)
        return ToolArgumentRecoveryResult(
            args=dict(fallback),
            strategy="regex_fallback",
            degraded=True,
            safe=safe,
        )

    logger.warning(" Tool argument recovery failed for %s", tool_name)
    return ToolArgumentRecoveryResult(args={}, strategy="failed", degraded=True, safe=False)


def extract_json_from_malformed_response(args_str: str) -> dict[str, object]:
    """Extract JSON from malformed LLM response.

    Some LLMs append extra content after the JSON object (e.g., markdown markers like ]<|FunctionCallEnd|>).
    This function attempts to extract just the JSON part.

    Args:
        args_str: The raw arguments string from LLM

    Returns:
        Parsed JSON dictionary

    Raises:
        json.JSONDecodeError: If JSON cannot be extracted
    """
    # Strip leading/trailing whitespace and remove common artifacts
    args_str = _strip_common_artifacts(args_str)
    args_str = re.sub(r"\]\s*$", "", args_str, flags=re.DOTALL)

    # Try to find the JSON object boundaries
    if args_str.startswith("{"):
        depth = 0
        in_string = False
        escape_next = False
        end_pos = -1

        for i, char in enumerate(args_str):
            if escape_next:
                escape_next = False
                continue

            if char == "\\":
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if not in_string:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end_pos = i + 1
                        break

        if end_pos > 0:
            args_str = args_str[:end_pos]

    return cast("dict[str, object]", json.loads(args_str))

"""LiteLLM utility functions


[INPUT]
- dataclasses::dataclass (POS: recovery result data structure)
- json::json (POS: Python JSON library)
- re::re (POS: Python regex library)

[OUTPUT]
- ToolArgumentRecoveryResult: tool argument recovery result
- fix_invalid_json_escapes(): fix invalid JSON escape sequences
- extract_json_from_malformed_response(): extract JSON from malformed responses
- parse_tool_call_arguments_with_recovery(): unified schema-aware tool argument fault-tolerant recovery

[POS]
LiteLLM utility functions. Provides JSON processing tools for handling LLM-generated malformed JSON.
Fixes invalid escapes, extracts pure JSON content, and performs schema-aware fault-tolerant parsing.
As the utility layer, depended on by adapters.converters and adapters.tool_call_parsers.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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


_LITERAL_PREFIXES: dict[str, str] = {
    "t": "true",
    "tr": "true",
    "tru": "true",
    "f": "false",
    "fa": "false",
    "fal": "false",
    "fals": "false",
    "n": "null",
    "nu": "null",
    "nul": "null",
}
_LITERAL_TAIL_RE = re.compile(r"[{,:\[]\s*(t(?:r(?:u)?)?|f(?:a(?:l(?:s)?)?)?|n(?:u(?:l)?)?)\s*$")
_DANGLING_KEY_RE = re.compile(r'"\s*:\s*$')


def _close_truncated_json(text: str) -> str:
    candidate = text.rstrip()
    if not candidate:
        return candidate

    in_string = False
    escape_next = False
    # Stack tracks nesting order so closers are emitted in correct sequence
    stack: list[str] = []

    for char in candidate:
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in ("{", "["):
            stack.append(char)
        elif char in ("}", "]") and stack:
            stack.pop()

    if in_string:
        # Odd trailing backslashes would escape the closing quote — strip the last one
        trailing = len(candidate) - len(candidate.rstrip("\\"))
        if trailing % 2 == 1:
            candidate = candidate[:-1]
        candidate += '"'

    candidate = re.sub(r",\s*$", "", candidate)
    # Fix truncated numeric fragments: sci-notation, trailing dot, bare minus
    candidate = re.sub(r"(\d[eE][+-]?)$", r"\g<1>0", candidate)
    candidate = re.sub(r"(\d)\.$", r"\g<1>.0", candidate)
    candidate = re.sub(r"([:,\[]\s*)-\s*$", r"\g<1>0", candidate)
    literal_match = _LITERAL_TAIL_RE.search(candidate)
    if literal_match:
        candidate = candidate[: literal_match.start(1)] + _LITERAL_PREFIXES[literal_match.group(1)]
    if _DANGLING_KEY_RE.search(candidate):
        candidate += " null"
    for opener in reversed(stack):
        candidate += "}" if opener == "{" else "]"
    return candidate


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


def parse_tool_call_arguments_with_recovery(
    args: str | dict[str, object],
    tool_name: str,
    tool_schema: Mapping[str, Any] | None = None,
) -> ToolArgumentRecoveryResult:
    """Recover malformed tool-call argument JSON using a strict staged pipeline.

    Supports 7 recovery strategies:
    1. Python None → JSON null (Weak model outputs Python literals)
    2. Standard JSON parsing
    3. Invalid escape sequence fixing
    4. Long text field repair (schema-aware)
    5. Truncated JSON completion
    6. Malformed JSON extraction
    7. Excess closing delimiter removal (Weak model outputs excess} or ])
    8. Regex fallback (marked as unsafe)
    """
    if isinstance(args, dict):
        return ToolArgumentRecoveryResult(args=args, strategy="dict_input")

    normalized = _strip_common_artifacts(args)

    # Strategy 0: Python None → JSON null
    if "None" in normalized:
        python_to_json = re.sub(r"\bNone\b", "null", normalized)
        if python_to_json != normalized:
            parsed = _load_json_object(python_to_json)
            if parsed is not None:
                return ToolArgumentRecoveryResult(args=parsed, strategy="python_none_to_null", degraded=True)
            normalized = python_to_json

    parsed = _load_json_object(normalized)
    if parsed is not None:
        return ToolArgumentRecoveryResult(args=parsed, strategy="standard_json")

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

        truncated_repaired = _close_truncated_json(repaired)
        parsed = _load_json_object(truncated_repaired)
        if parsed is not None:
            return ToolArgumentRecoveryResult(
                args=parsed,
                strategy=f"long_text_then_truncated_completion:{field_name}",
            )

    truncated = _close_truncated_json(escaped)
    if truncated != escaped:
        parsed = _load_json_object(truncated)
        if parsed is not None:
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

    return json.loads(args_str)


def get_unsupported_models() -> list[str]:
    return ["qwen-plus"]


def should_skip_response_format(model: str) -> bool:
    unsupported_models = get_unsupported_models()
    return any(unsupported in (model or "") for unsupported in unsupported_models)


_KIMI_TOOL_CALL_MIN_TEMP = 1.0
_KIMI_PREFIXES = ("moonshot/", "kimi/")


def _needs_temperature_floor(model: str) -> bool:
    """Kimi K2.5 requires temperature >= 1.0 when using function calling."""
    lower = (model or "").lower()
    return any(lower.startswith(p) for p in _KIMI_PREFIXES)


def clean_model_kwargs(kwargs: dict, model: str, additional_remove_keys: list[str] | None = None) -> dict:
    if additional_remove_keys is None:
        additional_remove_keys = []
    remove_keys = ["_in_fallback", "_json_mode_fallback", *additional_remove_keys]
    if should_skip_response_format(model):
        remove_keys.append("response_format")
    cleaned = {k: v for k, v in kwargs.items() if k not in remove_keys}
    if "model_kwargs" in cleaned and isinstance(cleaned["model_kwargs"], dict):
        cleaned["model_kwargs"] = {k: v for k, v in cleaned["model_kwargs"].items() if k not in remove_keys}

    if _needs_temperature_floor(model):
        temp = cleaned.get("temperature")
        if isinstance(temp, (int, float)) and temp < _KIMI_TOOL_CALL_MIN_TEMP:
            cleaned["temperature"] = _KIMI_TOOL_CALL_MIN_TEMP

    return cleaned

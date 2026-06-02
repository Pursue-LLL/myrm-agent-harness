"""LLM output parser for policy generation responses.

Handles parsing, cleaning, and normalizing LLM output into a valid
SecurityConfig-compatible dict.

[INPUT]
- Raw LLM response text (expected JSON)

[OUTPUT]
- parse_policy_response(): cleaned SecurityConfig dict
- PolicyParseError: raised on unrecoverable parse failures

[POS]
Robust parser with multi-strategy fallback for LLM output variance.
"""

from __future__ import annotations

import json
import re


class PolicyParseError(ValueError):
    """Raised when LLM output cannot be parsed into a valid policy config."""


_VALID_TOP_KEYS = frozenset({
    "permissions",
    "pathPolicy",
    "privacyPolicy",
    "networkAllowlist",
    "domainHitlEnabled",
    "capabilities",
    "approvalTimeoutSeconds",
    "approvalTimeoutBehavior",
    "autoReviewEnabled",
})

_VALID_ACTIONS = frozenset({"allow", "ask", "deny"})
_VALID_PII_ACTIONS = frozenset({"warn", "redact", "pseudonymize", "block"})


def parse_policy_response(raw_text: str) -> dict[str, object]:
    """Parse LLM response text into a SecurityConfig-compatible dict.

    Handles common LLM output quirks:
    - Markdown code blocks (```json ... ```)
    - Leading/trailing whitespace or explanation text
    - Partial JSON extraction

    Args:
        raw_text: Raw text response from LLM.

    Returns:
        Parsed and cleaned dict with only valid SecurityConfig keys.

    Raises:
        PolicyParseError: If parsing fails after all recovery attempts.
    """
    cleaned = _strip_markdown_blocks(raw_text.strip())

    parsed = _try_parse_json(cleaned)
    if parsed is None:
        extracted = _extract_json_object(cleaned)
        if extracted:
            parsed = _try_parse_json(extracted)

    if parsed is None:
        raise PolicyParseError(
            f"Failed to parse LLM output as JSON. Raw output (first 200 chars): {raw_text[:200]}"
        )

    if not isinstance(parsed, dict):
        raise PolicyParseError(
            f"Expected JSON object, got {type(parsed).__name__}"
        )

    return _normalize_config(parsed)


def _strip_markdown_blocks(text: str) -> str:
    """Remove markdown code block wrappers."""
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def _try_parse_json(text: str) -> dict[str, object] | list[object] | None:
    """Attempt JSON parse, return None on failure."""
    try:
        return json.loads(text)  # type: ignore[return-value]
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_json_object(text: str) -> str | None:
    """Extract the first JSON object from text with surrounding noise."""
    brace_start = text.find("{")
    if brace_start == -1:
        return None

    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start : i + 1]
    return None


def _normalize_config(raw: dict[str, object]) -> dict[str, object]:
    """Filter and normalize parsed config to valid keys and values."""
    result: dict[str, object] = {}

    for key in _VALID_TOP_KEYS:
        if key in raw:
            result[key] = raw[key]

    if "permissions" in result:
        result["permissions"] = _normalize_permissions(result["permissions"])

    if "privacyPolicy" in result:
        result["privacyPolicy"] = _normalize_privacy(result["privacyPolicy"])

    if "networkAllowlist" in result:
        val = result["networkAllowlist"]
        if isinstance(val, list):
            result["networkAllowlist"] = [str(d).strip().lower() for d in val if d]
        else:
            del result["networkAllowlist"]

    if "pathPolicy" in result:
        result["pathPolicy"] = _normalize_path_policy(result["pathPolicy"])

    if "approvalTimeoutSeconds" in result:
        val = result["approvalTimeoutSeconds"]
        if isinstance(val, (int, float)) and 1 <= val <= 3600:
            result["approvalTimeoutSeconds"] = int(val)
        else:
            del result["approvalTimeoutSeconds"]

    if "approvalTimeoutBehavior" in result and result["approvalTimeoutBehavior"] not in ("deny", "allow"):
        del result["approvalTimeoutBehavior"]

    return result


def _normalize_permissions(raw: object) -> dict[str, object]:
    """Normalize permissions to valid format."""
    if not isinstance(raw, dict):
        return {}

    result: dict[str, object] = {}
    for perm, value in raw.items():
        perm_str = str(perm)
        if isinstance(value, str) and value in _VALID_ACTIONS:
            result[perm_str] = value
        elif isinstance(value, dict):
            nested: dict[str, str] = {}
            for pattern, action in value.items():
                if isinstance(action, str) and action in _VALID_ACTIONS:
                    nested[str(pattern)] = action
            if nested:
                result[perm_str] = nested
    return result


def _normalize_privacy(raw: object) -> dict[str, object]:
    """Normalize privacyPolicy to valid format."""
    if not isinstance(raw, dict):
        return {}

    result: dict[str, object] = {}
    if "enabled" in raw:
        result["enabled"] = bool(raw["enabled"])
    if "s2Action" in raw and raw["s2Action"] in _VALID_PII_ACTIONS:
        result["s2Action"] = raw["s2Action"]
    if "s3Action" in raw and raw["s3Action"] in _VALID_PII_ACTIONS:
        result["s3Action"] = raw["s3Action"]
    if "deepScan" in raw:
        result["deepScan"] = bool(raw["deepScan"])
    return result


def _normalize_path_policy(raw: object) -> dict[str, object]:
    """Normalize pathPolicy to valid format."""
    if not isinstance(raw, dict):
        return {}

    result: dict[str, object] = {}
    if "allowedRoots" in raw and isinstance(raw["allowedRoots"], list):
        result["allowedRoots"] = [str(p) for p in raw["allowedRoots"] if p]
    if "forbiddenPaths" in raw and isinstance(raw["forbiddenPaths"], list):
        result["forbiddenPaths"] = [str(p) for p in raw["forbiddenPaths"] if p]
    return result

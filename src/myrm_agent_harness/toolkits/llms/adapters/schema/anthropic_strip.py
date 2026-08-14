"""Anthropic/Claude JSON Schema keyword stripping.

Anthropic's Tool Use API supports only a subset of JSON Schema. Keywords like
``minimum``, ``maxItems``, ``pattern``, ``format``, ``title`` and ``default``
cause 400 errors. This module strips those keywords recursively and folds the
validation constraints into ``description`` so the LLM still understands the
intended constraints.

[INPUT]
- A tool parameters JSON Schema dict.

[OUTPUT]
- is_anthropic_model: Return True when *model_name* targets an Anthropic/Claude provider.
- strip_anthropic_unsupported: Recursively strip unsupported keywords, folding constraints into ``description``.

[POS]
Anthropic-specific tool schema sanitization for OpenAI-compatible provider normalization.
"""

from __future__ import annotations

_ANTHROPIC_SUPPORTED_KEYS = frozenset(
    {
        "type",
        "properties",
        "required",
        "items",
        "additionalProperties",
        "anyOf",
        "oneOf",
        "allOf",
        "not",
        "$ref",
        "$defs",
        "definitions",
        "description",
        "enum",
        "prefixItems",
    }
)


def is_anthropic_model(model_name: str | None) -> bool:
    """Return True if *model_name* targets an Anthropic/Claude provider."""
    if not model_name:
        return False
    lowered = model_name.lower()
    return "claude" in lowered or "anthropic" in lowered


def _build_constraint_hint(unsupported: dict[str, object]) -> str:
    """Build a compact human-readable hint from stripped constraint keywords.

    Returns an empty string when no meaningful constraints were removed.
    """
    parts: list[str] = []

    lo = unsupported.get("minimum", unsupported.get("exclusiveMinimum"))
    hi = unsupported.get("maximum", unsupported.get("exclusiveMaximum"))
    if lo is not None and hi is not None:
        parts.append(f"range: {lo}–{hi}")
    elif lo is not None:
        parts.append(f"min: {lo}")
    elif hi is not None:
        parts.append(f"max: {hi}")

    min_len = unsupported.get("minLength")
    max_len = unsupported.get("maxLength")
    if min_len is not None or max_len is not None:
        parts.append(f"length: {min_len or 0}–{max_len or '∞'}")

    min_items = unsupported.get("minItems")
    max_items = unsupported.get("maxItems")
    if min_items is not None or max_items is not None:
        parts.append(f"items: {min_items or 0}–{max_items or '∞'}")

    if unsupported.get("uniqueItems"):
        parts.append("unique items")

    pat = unsupported.get("pattern")
    if pat is not None:
        parts.append(f"pattern: {pat}")

    fmt = unsupported.get("format")
    if fmt is not None:
        parts.append(f"format: {fmt}")

    default = unsupported.get("default")
    if default is not None:
        parts.append(f"default: {default}")

    return ", ".join(parts)


def strip_anthropic_unsupported(schema: dict[str, object]) -> dict[str, object]:
    """Recursively strip JSON Schema keywords unsupported by Anthropic.

    Removed validation constraints are folded into ``description`` so the
    LLM retains semantic awareness of the original intent.
    """
    cleaned: dict[str, object] = {}
    unsupported: dict[str, object] = {}

    for key, value in schema.items():
        if key in _ANTHROPIC_SUPPORTED_KEYS:
            cleaned[key] = value
        else:
            unsupported[key] = value

    hint = _build_constraint_hint(unsupported)
    if hint:
        desc = str(cleaned.get("description", ""))
        cleaned["description"] = f"{desc} ({hint})".lstrip() if desc else f"({hint})"

    props = cleaned.get("properties")
    if isinstance(props, dict):
        cleaned["properties"] = {
            k: strip_anthropic_unsupported(v) if isinstance(v, dict) else v for k, v in props.items()
        }

    items = cleaned.get("items")
    if isinstance(items, dict):
        cleaned["items"] = strip_anthropic_unsupported(items)

    for kw in ("anyOf", "oneOf", "allOf"):
        branches = cleaned.get(kw)
        if isinstance(branches, list):
            cleaned[kw] = [strip_anthropic_unsupported(b) if isinstance(b, dict) else b for b in branches]

    not_schema = cleaned.get("not")
    if isinstance(not_schema, dict):
        cleaned["not"] = strip_anthropic_unsupported(not_schema)

    prefix_items = cleaned.get("prefixItems")
    if isinstance(prefix_items, list):
        cleaned["prefixItems"] = [
            strip_anthropic_unsupported(item) if isinstance(item, dict) else item for item in prefix_items
        ]

    return cleaned

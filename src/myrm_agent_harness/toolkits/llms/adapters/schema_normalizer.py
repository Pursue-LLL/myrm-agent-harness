"""Tool Schema Normalizer for OpenAI-compatible Providers

MCP tools use full JSON Schema, but OpenAI-compatible providers reject:
- top-level anyOf/oneOf/allOf/enum/not
- nullable patterns like anyOf: [{type: X}, {type: null}]
- $ref / $defs inline definitions
- missing ``type`` on property schemas (strict providers like Moonshot/Kimi)
- ``nullable`` keyword (OpenAPI 3.0 extension, non-standard JSON Schema)
- null/empty-string values in enum arrays on scalar types
- tuple-style ``items`` arrays (positional element schemas)

Additionally, Anthropic's Tool Use API supports only a subset of JSON Schema.
Keywords like ``minimum``, ``maxItems``, ``pattern``, ``format``, ``title``,
and ``default`` cause 400 errors.  When the target model is Anthropic/Claude,
this module strips unsupported keywords and folds validation constraints into
the ``description`` field so the LLM still understands the intent.

[INPUT]
- (none)

[OUTPUT]
- normalize_tool_schema: Normalize an OpenAI-format tool schema for provider compatibility

[POS]
Tool Schema Normalizer for OpenAI-compatible Providers
"""

from __future__ import annotations

import copy

_COMPOSITE_KEYWORDS = frozenset({"anyOf", "oneOf", "allOf"})
_REF_PREFIXES = ("#/$defs/", "#/definitions/")

_ANTHROPIC_SUPPORTED_KEYS = frozenset({
    "type", "properties", "required", "items", "additionalProperties",
    "anyOf", "oneOf", "allOf", "not",
    "$ref", "$defs", "definitions",
    "description", "enum",
    "prefixItems",
})


def normalize_tool_schema(
    tool: dict[str, object],
    *,
    model_name: str | None = None,
) -> dict[str, object]:
    """Normalize an OpenAI-format tool schema for provider compatibility.

    Processes the ``function.parameters`` sub-tree in-place (on a deep copy)
    to remove JSON Schema constructs that strict providers reject.

    When *model_name* indicates an Anthropic/Claude model, additionally strips
    unsupported JSON Schema keywords (``minimum``, ``maxItems``, ``title``,
    ``default``, etc.) and folds validation constraints into ``description``.

    Args:
        tool: OpenAI-format tool dict ``{type: "function", function: {...}}``.
        model_name: LLM model identifier (e.g. ``"claude-sonnet-4-20250514"``).
            Used to activate provider-specific schema sanitization.

    Returns:
        A normalized copy of the tool dict.
    """
    tool = copy.deepcopy(tool)
    func = tool.get("function")
    if not isinstance(func, dict):
        return tool

    params = func.get("parameters")
    if not isinstance(params, dict):
        return tool

    params = _resolve_defs(params)
    params = _ensure_object_type(params)
    _normalize_properties(params)

    if _is_anthropic_model(model_name):
        params = _strip_anthropic_unsupported(params)

    func["parameters"] = params
    return tool


def _resolve_defs(schema: dict[str, object]) -> dict[str, object]:
    """Inline ``$ref`` references using ``$defs`` / ``definitions``."""
    defs: dict[str, object] = {}
    for key in ("$defs", "definitions"):
        raw = schema.get(key)
        if isinstance(raw, dict):
            defs.update(raw)

    if not defs:
        return schema

    resolved = _inline_refs(schema, defs)
    if isinstance(resolved, dict):
        resolved.pop("$defs", None)
        resolved.pop("definitions", None)
    return resolved  # type: ignore[return-value]


def _inline_refs(
    node: object,
    defs: dict[str, object],
    depth: int = 0,
) -> object:
    """Recursively replace ``$ref`` pointers with their definitions."""
    if depth > 20:
        return node

    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            for prefix in _REF_PREFIXES:
                if ref.startswith(prefix):
                    def_name = ref[len(prefix) :]
                    if def_name in defs:
                        resolved = copy.deepcopy(defs[def_name])
                        return _inline_refs(resolved, defs, depth + 1)
                    break

        return {k: _inline_refs(v, defs, depth + 1) for k, v in node.items()}

    if isinstance(node, list):
        return [_inline_refs(item, defs, depth + 1) for item in node]

    return node


def _ensure_object_type(schema: dict[str, object]) -> dict[str, object]:
    """Ensure the top-level schema is ``{type: "object"}``.

    If the schema uses a top-level composite keyword (anyOf/oneOf/allOf),
    attempt to extract a single object branch.  Falls back to a permissive
    empty object schema as a safe default.
    """
    if schema.get("type") == "object":
        return schema

    for kw in _COMPOSITE_KEYWORDS:
        branches = schema.get(kw)
        if not isinstance(branches, list):
            continue

        obj_branches = [b for b in branches if isinstance(b, dict) and b.get("type") == "object"]
        if len(obj_branches) == 1:
            merged = obj_branches[0]
            for preserve_key in ("description", "default"):
                if preserve_key in schema and preserve_key not in merged:
                    merged[preserve_key] = schema[preserve_key]
            return merged

        non_null = [b for b in branches if not (isinstance(b, dict) and b.get("type") == "null")]
        if len(non_null) == 1 and isinstance(non_null[0], dict) and non_null[0].get("type") == "object":
            return non_null[0]

    if "properties" in schema:
        schema.setdefault("type", "object")
        return schema

    return {"type": "object", "properties": {}, "additionalProperties": True}


def _normalize_properties(schema: dict[str, object]) -> None:
    """Recursively normalize property schemas within an object."""
    props = schema.get("properties")
    if not isinstance(props, dict):
        return

    for prop_name, prop_schema in list(props.items()):
        if isinstance(prop_schema, dict):
            props[prop_name] = _normalize_property(prop_schema)


def _normalize_property(prop: dict[str, object]) -> dict[str, object]:
    """Normalize a single property schema, handling nullable and composite types."""
    prop.pop("nullable", None)

    for kw in _COMPOSITE_KEYWORDS:
        branches = prop.get(kw)
        if not isinstance(branches, list):
            continue

        non_null = [b for b in branches if not (isinstance(b, dict) and b.get("type") == "null")]

        if kw == "allOf" and len(non_null) > 1:
            merged = _merge_allof_branches(non_null)
            if merged is not None:
                _preserve_metadata(prop, merged)
                _normalize_nested(merged)
                return _finalize_property(merged)

        if len(non_null) == 1 and isinstance(non_null[0], dict):
            result = dict(non_null[0])
            _preserve_metadata(prop, result)
            _normalize_nested(result)
            return _finalize_property(result)

        if non_null:
            first = non_null[0]
            if isinstance(first, dict):
                result = dict(first)
                _preserve_metadata(prop, result)
                _normalize_nested(result)
                return _finalize_property(result)

    _normalize_nested(prop)
    return _finalize_property(prop)


_METADATA_KEYS = ("description", "default", "title", "examples")


def _preserve_metadata(source: dict[str, object], target: dict[str, object]) -> None:
    """Copy metadata keys from source to target if not already present."""
    for key in _METADATA_KEYS:
        if key in source and key not in target:
            target[key] = source[key]


def _merge_allof_branches(branches: list[object]) -> dict[str, object] | None:
    """Merge multiple allOf object branches into a single schema.

    Only merges when all branches are ``{type: "object"}``.
    Combines ``properties`` and ``required`` fields.
    """
    merged_props: dict[str, object] = {}
    merged_required: list[str] = []

    for branch in branches:
        if not isinstance(branch, dict) or branch.get("type") != "object":
            return None
        props = branch.get("properties")
        if isinstance(props, dict):
            merged_props.update(props)
        req = branch.get("required")
        if isinstance(req, list):
            merged_required.extend(req)

    result: dict[str, object] = {"type": "object", "properties": merged_props}
    if merged_required:
        result["required"] = list(dict.fromkeys(merged_required))
    return result


def _normalize_nested(schema: dict[str, object]) -> None:
    """Recurse into nested object / array schemas."""
    if schema.get("type") == "object":
        _normalize_properties(schema)

    items = schema.get("items")
    if isinstance(items, list):
        schema["items"] = _normalize_property(items[0] if items else {})
    elif isinstance(items, dict):
        schema["items"] = _normalize_property(items)


def _finalize_property(schema: dict[str, object]) -> dict[str, object]:
    """Apply type inference then enum cleanup — order matters."""
    _infer_missing_type(schema)
    _clean_enum(schema)
    return schema


def _infer_missing_type(schema: dict[str, object]) -> None:
    """Infer ``type`` when absent — strict providers require it on every node.

    When type is inferred as "object", recursively normalizes child properties
    that may have been skipped during the initial _normalize_nested pass.
    """
    if "type" in schema and schema["type"] not in {None, ""}:
        return

    if "properties" in schema or "required" in schema or "additionalProperties" in schema:
        schema["type"] = "object"
        _normalize_properties(schema)
    elif "items" in schema or "prefixItems" in schema:
        schema["type"] = "array"
    elif "enum" in schema and isinstance(schema["enum"], list) and schema["enum"]:
        sample = schema["enum"][0]
        if isinstance(sample, bool):
            schema["type"] = "boolean"
        elif isinstance(sample, int):
            schema["type"] = "integer"
        elif isinstance(sample, float):
            schema["type"] = "number"
        else:
            schema["type"] = "string"
    else:
        schema["type"] = "string"


def _clean_enum(schema: dict[str, object]) -> None:
    """Remove null and empty-string values from enum arrays on scalar types."""
    enum_val = schema.get("enum")
    if not isinstance(enum_val, list):
        return

    node_type = schema.get("type")
    if node_type not in {"string", "integer", "number", "boolean"}:
        return

    cleaned = [v for v in enum_val if v is not None and v != ""]
    if cleaned:
        schema["enum"] = cleaned
    else:
        schema.pop("enum", None)


# ---------------------------------------------------------------------------
# Anthropic-specific: strip unsupported JSON Schema keywords
# ---------------------------------------------------------------------------


def _is_anthropic_model(model_name: str | None) -> bool:
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


def _strip_anthropic_unsupported(schema: dict[str, object]) -> dict[str, object]:
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
            k: _strip_anthropic_unsupported(v) if isinstance(v, dict) else v
            for k, v in props.items()
        }

    items = cleaned.get("items")
    if isinstance(items, dict):
        cleaned["items"] = _strip_anthropic_unsupported(items)

    for kw in ("anyOf", "oneOf", "allOf"):
        branches = cleaned.get(kw)
        if isinstance(branches, list):
            cleaned[kw] = [
                _strip_anthropic_unsupported(b) if isinstance(b, dict) else b
                for b in branches
            ]

    not_schema = cleaned.get("not")
    if isinstance(not_schema, dict):
        cleaned["not"] = _strip_anthropic_unsupported(not_schema)

    prefix_items = cleaned.get("prefixItems")
    if isinstance(prefix_items, list):
        cleaned["prefixItems"] = [
            _strip_anthropic_unsupported(item) if isinstance(item, dict) else item
            for item in prefix_items
        ]

    return cleaned

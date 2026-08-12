"""Tool Schema Normalizer for OpenAI-compatible Providers

MCP tools use full JSON Schema, but OpenAI-compatible providers reject:
- top-level anyOf/oneOf/allOf/enum/not
- nullable patterns like anyOf: [{type: X}, {type: null}]
- $ref / $defs inline definitions
- missing ``type`` on property schemas (strict providers like Moonshot/Kimi)
- ``nullable`` keyword (OpenAPI 3.0 extension, non-standard JSON Schema)
- null/empty-string values in enum arrays on scalar types
- tuple-style ``items`` arrays (positional element schemas)
- ``required`` entries referencing fields absent from ``properties``
  (Gemini/Vertex AI and OpenAI strict mode reject these with 400)

Top-level anyOf/oneOf/allOf object branches are merged into a flat properties
set (allOf conjunctively, anyOf/oneOf as alternatives with exclusivity hints).
Nested property-level anyOf/oneOf unions of multiple object branches are merged
the same way so no branch's parameters are hidden from the LLM; redefined
properties keep the union (anyOf/oneOf) or intersection (allOf) of their
const/enum values.  Branch/const-union merging lives in ``property_merge``.

When the target model is Anthropic/Claude, unsupported JSON Schema keywords are
stripped and constraints are folded into ``description`` — see
``anthropic_strip``.

[INPUT]
- adapters.schema.property_merge (POS: Tool schema property-merge helpers for OpenAI-compatible provider normalization)
- adapters.schema.anthropic_strip (POS: Anthropic-specific tool schema sanitization for OpenAI-compatible provider normalization)

[OUTPUT]
- normalize_tool_schema: Normalize an OpenAI-format tool schema for provider compatibility.
  Top-level anyOf/oneOf/allOf object branches are merged into a flat properties set
  (allOf conjunctively, anyOf/oneOf as alternatives with exclusivity hints).  Nested
  property-level anyOf/oneOf unions of multiple object branches are merged the same
  way so no branch's parameters are hidden from the LLM; redefined properties keep
  the union (anyOf/oneOf) or intersection (allOf) of their const/enum values.

[POS]
Tool Schema Normalizer for OpenAI-compatible Providers
"""

from __future__ import annotations

import copy
import logging

from myrm_agent_harness.toolkits.llms.adapters.schema.anthropic_strip import (
    is_anthropic_model,
    strip_anthropic_unsupported,
)
from myrm_agent_harness.toolkits.llms.adapters.schema.property_merge import (
    apply_union_hint,
    merge_allof_branches,
    merge_union_object_branches,
    preserve_metadata,
)

logger = logging.getLogger(__name__)

_COMPOSITE_KEYWORDS = frozenset({"anyOf", "oneOf", "allOf"})
_REF_PREFIXES = ("#/$defs/", "#/definitions/")


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

    if is_anthropic_model(model_name):
        params = strip_anthropic_unsupported(params)

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
    """Recursively replace ``$ref`` pointers with their definitions.

    Sibling keys next to ``$ref`` (e.g. an overriding ``description``) are
    merged onto the resolved definition so field guidance survives inlining —
    matching the inbound ``flatten_json_schema`` behavior.
    """
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
                        resolved = _inline_refs(resolved, defs, depth + 1)
                        if isinstance(resolved, dict):
                            for key, value in node.items():
                                if key != "$ref":
                                    resolved[key] = _inline_refs(value, defs, depth + 1)
                            return resolved
                        return resolved
                    break

        return {k: _inline_refs(v, defs, depth + 1) for k, v in node.items()}

    if isinstance(node, list):
        return [_inline_refs(item, defs, depth + 1) for item in node]

    return node


def _ensure_object_type(schema: dict[str, object]) -> dict[str, object]:
    """Ensure the top-level schema is ``{type: "object"}``.

    If the schema uses a top-level composite keyword (anyOf/oneOf/allOf),
    extract a single object branch, or merge multiple object branches into a
    flat property set (allOf conjunctively, anyOf/oneOf as alternatives).
    Falls back to a permissive empty object schema as a safe default.
    """
    if schema.get("type") == "object":
        return schema

    for kw in _COMPOSITE_KEYWORDS:
        branches = schema.get(kw)
        if not isinstance(branches, list):
            continue

        obj_branches = [
            b for b in branches if isinstance(b, dict) and b.get("type") == "object"
        ]
        if len(obj_branches) == 1:
            merged = obj_branches[0]
            for preserve_key in ("description", "default"):
                if preserve_key in schema and preserve_key not in merged:
                    merged[preserve_key] = schema[preserve_key]
            return merged

        if len(obj_branches) > 1:
            if kw == "allOf":
                allof_merged = merge_allof_branches(obj_branches)
                if allof_merged is not None:
                    for preserve_key in ("description", "default"):
                        if preserve_key in schema and preserve_key not in allof_merged:
                            allof_merged[preserve_key] = schema[preserve_key]
                    return allof_merged
            else:
                union_merged = merge_union_object_branches(obj_branches, keyword=kw)
                return apply_union_hint(union_merged, schema)

        non_null = [
            b for b in branches if not (isinstance(b, dict) and b.get("type") == "null")
        ]
        if (
            len(non_null) == 1
            and isinstance(non_null[0], dict)
            and non_null[0].get("type") == "object"
        ):
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

    req = schema.get("required")
    if isinstance(req, list):
        pruned = [r for r in req if r in props]
        if len(pruned) < len(req):
            logger.debug("Pruned orphan required entries: %s", set(req) - set(pruned))
        if pruned:
            schema["required"] = pruned
        else:
            del schema["required"]


def _normalize_property(prop: dict[str, object]) -> dict[str, object]:
    """Normalize a single property schema, handling nullable and composite types."""
    prop.pop("nullable", None)

    for kw in _COMPOSITE_KEYWORDS:
        branches = prop.get(kw)
        if not isinstance(branches, list):
            continue

        non_null = [
            b for b in branches if not (isinstance(b, dict) and b.get("type") == "null")
        ]

        if kw == "allOf" and len(non_null) > 1:
            merged = merge_allof_branches(non_null)
            if merged is not None:
                preserve_metadata(prop, merged)
                _normalize_nested(merged)
                return _finalize_property(merged)

        # Multiple object branches under anyOf/oneOf (e.g. a zod union of
        # objects) — merge *all* of them so no branch's parameters stay
        # hidden from the LLM.  A single object branch and mixed primitive
        # unions fall through to the branch-selection logic below.
        if kw in ("anyOf", "oneOf") and len(non_null) > 1:
            object_branches = [
                b for b in non_null if isinstance(b, dict) and b.get("type") == "object"
            ]
            if len(object_branches) > 1:
                merged = merge_union_object_branches(object_branches, keyword=kw)
                merged = apply_union_hint(merged, prop)
                _normalize_nested(merged)
                return _finalize_property(merged)

        if len(non_null) == 1 and isinstance(non_null[0], dict):
            result = dict(non_null[0])
            preserve_metadata(prop, result)
            _normalize_nested(result)
            return _finalize_property(result)

        if non_null:
            first = non_null[0]
            if isinstance(first, dict):
                result = dict(first)
                preserve_metadata(prop, result)
                _normalize_nested(result)
                return _finalize_property(result)

    _normalize_nested(prop)
    return _finalize_property(prop)


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

    if (
        "properties" in schema
        or "required" in schema
        or "additionalProperties" in schema
    ):
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

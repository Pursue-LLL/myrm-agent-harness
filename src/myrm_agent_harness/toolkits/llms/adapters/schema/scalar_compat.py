"""Array-form ``type`` normalization for tool schemas.

JSON Schema permits ``type`` to be an array (``["string", "null"]``), which
Pydantic v1 ``Optional`` fields and older zod output emit. Strict
OpenAI-compatible providers reject the array form — some with HTTP 400 —
and the outbound normalizer's missing-type inference crashes on it (a
``list`` is unhashable when tested against a set). This module rewrites
array-form ``type`` into the single-type form the rest of the normalization
pipeline expects, before any composite-keyword logic runs:

- ``["X", "null"]`` -> ``type: X`` plus ``nullable: true`` (the hint keeps
  runtime argument coercion able to recognize nullability)
- ``["X", "Y"]`` (multiple non-null types) -> ``anyOf: [{type: X}, {type: Y}]``
  so no branch is dropped
- ``["null"]`` -> ``type: "null"``
- ``[]`` -> ``type`` removed so missing-type inference picks a concrete one

The rewrite is deterministic and idempotent: a schema without array-form
``type`` passes through unchanged.

[INPUT]
- raw MCP ``inputSchema`` / tool ``parameters`` dicts (Pydantic v1 Optional,
  older zod output, OpenAPI gateway schemas)

[OUTPUT]
- normalize_type_arrays: Rewrite array-form ``type`` into scalar/anyOf/null form.

[POS]
Tool schema scalar-compatibility normalization for OpenAI-compatible providers.
"""

from __future__ import annotations

_COMPOSITE_KEYS = frozenset({"anyOf", "oneOf", "allOf"})


def normalize_type_arrays(node: object) -> object:
    """Return a copy of *node* with array-form ``type`` normalized."""
    if isinstance(node, list):
        return [normalize_type_arrays(item) for item in node]
    if not isinstance(node, dict):
        return node

    out: dict[str, object] = {}
    for key, value in node.items():
        if key == "type" and isinstance(value, list):
            _rewrite_type_list(out, value, _has_composite(node))
        else:
            out[key] = normalize_type_arrays(value)
    return out


def _has_composite(node: dict[str, object]) -> bool:
    return any(isinstance(node.get(key), list) for key in _COMPOSITE_KEYS)


def _rewrite_type_list(
    out: dict[str, object],
    type_values: list[object],
    has_composite: bool,
) -> None:
    non_null = [t for t in type_values if isinstance(t, str) and t != "null"]
    has_null = "null" in type_values
    if len(non_null) == 1:
        out["type"] = non_null[0]
        if has_null:
            out["nullable"] = True
        return
    if len(non_null) > 1:
        if has_composite:
            # The node already carries a composite keyword; a parallel
            # ``anyOf`` list would be redundant. Drop the array form and
            # keep only the nullability hint.
            if has_null:
                out["nullable"] = True
            return
        out["anyOf"] = [{"type": t} for t in non_null]
        if has_null:
            out["nullable"] = True
        return
    if has_null:
        out["type"] = "null"
    # An empty array carries no information — drop it so missing-type
    # inference (``_infer_missing_type``) fills in a concrete type.

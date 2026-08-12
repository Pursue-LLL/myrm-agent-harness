"""Property-level branch merging for provider-compatible tool schemas.

Merges object branches produced by JSON Schema composite keywords into a
single flat ``properties`` set. ``allOf`` branches are conjunctive — same-name
properties intersect (closed ``const``/``enum`` sets intersect, a closed set
conjoined with an open type keeps the closed set, an empty intersection keeps
the first definition). ``anyOf``/``oneOf`` branches are alternatives — the
exclusivity hint is folded into ``description``, and a property redefined
across branches keeps the union of its ``const``/``enum`` values so a
discriminator field exposes every branch.

[INPUT]
- object-branch JSON Schema dicts (``{type: "object", properties, required}``)

[OUTPUT]
- merge_allof_branches: Conjunctive merge of allOf object branches (required union, same-name properties intersect).
- merge_union_object_branches: Alternative merge of anyOf/oneOf object branches (required dropped, same-name const/enum union, exclusivity hint).
- apply_union_hint: Fold the exclusivity hint with the outer schema's description (outer description prefixed, never dropped).
- merge_union_property / intersect_property: Per-property union / intersection of const/enum value sets.
- preserve_metadata: Copy description/default/title/examples from source to target when absent.

[POS]
Tool schema property-merge helpers for OpenAI-compatible provider normalization.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

_METADATA_KEYS = ("description", "default", "title", "examples")


def preserve_metadata(source: dict[str, object], target: dict[str, object]) -> None:
    """Copy metadata keys from source to target if not already present."""
    for key in _METADATA_KEYS:
        if key in source and key not in target:
            target[key] = source[key]


def merge_allof_branches(
    branches: Sequence[dict[str, object]],
) -> dict[str, object] | None:
    """Merge multiple allOf object branches into a single schema.

    Only merges when all branches are ``{type: "object"}``. Combines
    ``properties`` and ``required`` fields; a property redefined across
    branches is merged conjunctively (``intersect_property``).
    """
    merged_props: dict[str, object] = {}
    merged_required: list[str] = []

    for branch in branches:
        if branch.get("type") != "object":
            return None
        props = branch.get("properties")
        if isinstance(props, dict):
            for name, prop_schema in props.items():
                existing = merged_props.get(name)
                if (
                    existing is not None
                    and isinstance(existing, dict)
                    and isinstance(prop_schema, dict)
                ):
                    merged_props[name] = intersect_property(existing, prop_schema)
                else:
                    merged_props[name] = prop_schema
        req = branch.get("required")
        if isinstance(req, list):
            merged_required.extend(req)

    result: dict[str, object] = {"type": "object", "properties": merged_props}
    if merged_required:
        result["required"] = list(dict.fromkeys(merged_required))
    return result


def merge_union_object_branches(
    branches: Sequence[dict[str, object]],
) -> dict[str, object]:
    """Merge multiple oneOf/anyOf object branches into a single flat schema.

    Union branches are alternatives: every branch's ``properties`` are merged,
    but ``required`` is dropped — merging it would force mutually-exclusive
    parameters to be supplied together. A property redefined across branches
    keeps the union of its ``const``/``enum`` values so a discriminator field
    exposes every branch. The alternative constraint is folded into
    ``description`` so the LLM still picks one valid combination.
    """
    merged_props: dict[str, object] = {}
    alternatives: list[list[str]] = []

    for branch in branches:
        if branch.get("type") != "object":
            continue
        props = branch.get("properties")
        if isinstance(props, dict):
            for name, prop_schema in props.items():
                existing = merged_props.get(name)
                if (
                    existing is not None
                    and isinstance(existing, dict)
                    and isinstance(prop_schema, dict)
                ):
                    merged_props[name] = merge_union_property(existing, prop_schema)
                else:
                    merged_props[name] = prop_schema
            alternatives.append(sorted(props))
        else:
            alternatives.append([])

    if not merged_props:
        return {"type": "object", "properties": {}, "additionalProperties": True}

    result: dict[str, object] = {"type": "object", "properties": merged_props}
    non_empty = [alt for alt in alternatives if alt]
    if len(non_empty) >= 2:
        groups = "; ".join(f"({', '.join(alt)})" for alt in non_empty)
        result["description"] = (
            f"Parameters are mutually exclusive alternatives — provide exactly one group: {groups}."
        )
    return result


def apply_union_hint(
    merged: dict[str, object], outer: dict[str, object]
) -> dict[str, object]:
    """Fold the branch-exclusivity hint with the outer schema's description.

    The exclusivity hint generated by the union merge becomes the merged
    schema's description; an outer description (if any) is prefixed rather
    than dropped so neither piece of guidance is lost.
    """
    hint = merged.get("description")
    if hint:
        del merged["description"]
    preserve_metadata(outer, merged)
    if hint:
        own = merged.get("description")
        merged["description"] = f"{own} {hint}".strip() if own else hint
    return merged


def _collect_const_enum(schema: dict[str, object]) -> list[object]:
    """Return the enumerable values of a property schema (``const`` → singleton)."""
    if "const" in schema:
        return [schema["const"]]
    enum_values = schema.get("enum")
    if isinstance(enum_values, list):
        return enum_values
    return []


def _json_value_key(value: object) -> str:
    """Stable string key for a JSON value, used for set membership."""
    try:
        return json.dumps(value, sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


def _dedupe_values(values: list[object]) -> list[object]:
    """Dedupe arbitrary JSON values while preserving first-seen order."""
    seen: set[str] = set()
    unique: list[object] = []
    for value in values:
        key = _json_value_key(value)
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def merge_union_property(
    existing: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    """Merge a property redefined across anyOf/oneOf branches (union).

    Keeps the union of closed ``const``/``enum`` values so a discriminator
    field exposes every branch; a closed set unioned with an open type widens
    to the open type (its domain already covers the closed set).
    """
    existing_values = _collect_const_enum(existing)
    incoming_values = _collect_const_enum(incoming)
    if existing_values and incoming_values:
        merged = {k: v for k, v in existing.items() if k != "const"}
        merged["enum"] = _dedupe_values(existing_values + incoming_values)
        existing_type = existing.get("type")
        if existing_type is not None and existing_type == incoming.get("type"):
            merged["type"] = existing_type
        return merged
    if existing_values or incoming_values:
        open_side = incoming if existing_values else existing
        return {k: v for k, v in open_side.items() if k not in ("const", "enum")}
    return dict(existing)


def intersect_property(
    existing: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    """Merge a property redefined across allOf branches (conjunction).

    A valid value must satisfy both: closed sets intersect; a closed set
    conjoined with an open type keeps the closed set; an empty intersection
    keeps the first definition rather than an unusable empty enum.
    """
    existing_values = _collect_const_enum(existing)
    incoming_values = _collect_const_enum(incoming)
    if existing_values and incoming_values:
        incoming_keys = {_json_value_key(value) for value in incoming_values}
        common = [
            value
            for value in existing_values
            if _json_value_key(value) in incoming_keys
        ]
        if common:
            merged = {k: v for k, v in existing.items() if k != "const"}
            merged["enum"] = _dedupe_values(common)
            existing_type = existing.get("type")
            if existing_type is not None and existing_type == incoming.get("type"):
                merged["type"] = existing_type
            return merged
        return dict(existing)
    if existing_values or incoming_values:
        closed = existing if existing_values else incoming
        return dict(closed)
    return dict(existing)

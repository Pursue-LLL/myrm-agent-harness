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
- merge_union_object_branches: Alternative merge of anyOf/oneOf object branches (required dropped except common-required promotion, same-name const/enum union, keyword-aware exclusivity hint — oneOf "exactly one group", anyOf "at least one").
- apply_union_hint: Fold the exclusivity hint with the outer schema's description (outer description prefixed, never dropped).
- merge_union_property / intersect_property: Per-property union / intersection of const/enum value sets, with branch metadata (title/description/default) merged symmetrically so no branch's guidance is dropped.
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
                if existing is not None and isinstance(existing, dict) and isinstance(prop_schema, dict):
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
    *,
    keyword: str,
) -> dict[str, object]:
    """Merge multiple oneOf/anyOf object branches into a single flat schema.

    Union branches are alternatives: every branch's ``properties`` are merged,
    but ``required`` is dropped — merging it would force mutually-exclusive
    parameters to be supplied together. A property redefined across branches
    keeps the union of its ``const``/``enum`` values so a discriminator field
    exposes every branch. A property required by *every* branch (e.g. the
    ``type`` discriminator of a oneOf union) is promoted to the top-level
    ``required`` — it is mandatory no matter which branch is chosen — and
    excluded from the exclusivity hint. The alternative constraint is folded
    into ``description`` so the LLM still picks one valid combination. The
    wording matches the real JSON Schema semantics: ``oneOf`` admits exactly
    one branch, ``anyOf`` admits at least one.
    """
    merged_props: dict[str, object] = {}
    alternatives: list[list[str]] = []
    required_counts: dict[str, int] = {}
    branch_count = 0

    for branch in branches:
        if branch.get("type") != "object":
            continue
        props = branch.get("properties")
        if isinstance(props, dict):
            branch_count += 1
            for name, prop_schema in props.items():
                existing = merged_props.get(name)
                if existing is not None and isinstance(existing, dict) and isinstance(prop_schema, dict):
                    merged_props[name] = merge_union_property(existing, prop_schema)
                else:
                    merged_props[name] = prop_schema
            alternatives.append(sorted(props))
        else:
            alternatives.append([])
            continue
        req = branch.get("required")
        if isinstance(req, list):
            for name in req:
                if isinstance(name, str) and name in props:
                    required_counts[name] = required_counts.get(name, 0) + 1

    if not merged_props:
        return {"type": "object", "properties": {}, "additionalProperties": True}

    # A property required by every alternative branch (e.g. the ``type``
    # discriminator of a oneOf union) is mandatory no matter which branch is
    # chosen — promote it so the LLM sees it as required instead of optional.
    common_required = {name for name, count in required_counts.items() if branch_count > 1 and count == branch_count}

    result: dict[str, object] = {"type": "object", "properties": merged_props}
    if common_required:
        result["required"] = sorted(common_required)

    non_empty = [alt for alt in alternatives if alt]
    if len(non_empty) >= 2:
        exclusive_groups = [[name for name in group if name not in common_required] for group in non_empty]
        meaningful = [group for group in exclusive_groups if group]
        if len(meaningful) >= 2:
            groups = "; ".join(f"({', '.join(alt)})" for alt in meaningful)
            if keyword == "oneOf":
                result["description"] = (
                    f"Parameters are mutually exclusive alternatives — provide exactly one group: {groups}."
                )
            else:
                result["description"] = f"Parameters are alternatives — provide at least one of these groups: {groups}."
    return result


def apply_union_hint(merged: dict[str, object], outer: dict[str, object]) -> dict[str, object]:
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


def _merge_metadata(
    existing: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    """Merge ``title``/``description``/``default`` from both property sides.

    ``title`` and ``default`` prefer the first definition; ``description``
    dedupes equal text and concatenates differing text so a discriminator
    field redefined across branches keeps every branch's guidance instead of
    silently dropping the second definition. Mirrors the inbound union /
    intersection merge semantics.
    """
    merged: dict[str, object] = {}

    existing_title = existing.get("title")
    incoming_title = incoming.get("title")
    if existing_title or incoming_title:
        merged["title"] = existing_title or incoming_title

    existing_desc = existing.get("description")
    incoming_desc = incoming.get("description")
    if existing_desc and incoming_desc:
        if existing_desc == incoming_desc:
            merged["description"] = existing_desc
        else:
            merged["description"] = f"{existing_desc} {incoming_desc}"
    elif existing_desc or incoming_desc:
        merged["description"] = existing_desc or incoming_desc

    if "default" in existing or "default" in incoming:
        merged["default"] = existing["default"] if "default" in existing else incoming["default"]
    return merged


def merge_union_property(
    existing: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    """Merge a property redefined across anyOf/oneOf branches (union).

    Keeps the union of closed ``const``/``enum`` values so a discriminator
    field exposes every branch; a closed set unioned with an open type widens
    to the open type (its domain already covers the closed set). Metadata from
    both sides is merged (``_merge_metadata``) so no branch's description is
    dropped.
    """
    existing_values = _collect_const_enum(existing)
    incoming_values = _collect_const_enum(incoming)
    if existing_values and incoming_values:
        merged = {k: v for k, v in existing.items() if k != "const"}
        merged["enum"] = _dedupe_values(existing_values + incoming_values)
        existing_type = existing.get("type")
        if existing_type is not None and existing_type == incoming.get("type"):
            merged["type"] = existing_type
        merged.update(_merge_metadata(existing, incoming))
        return merged
    if existing_values or incoming_values:
        const_side = existing if existing_values else incoming
        open_side = incoming if existing_values else existing
        merged = {k: v for k, v in open_side.items() if k not in ("const", "enum")}
        for meta_key in ("title", "description", "default"):
            if meta_key in const_side and meta_key not in merged:
                merged[meta_key] = const_side[meta_key]
        return merged
    return dict(existing)


def intersect_property(
    existing: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    """Merge a property redefined across allOf branches (conjunction).

    A valid value must satisfy both: closed sets intersect; a closed set
    conjoined with an open type keeps the closed set; an empty intersection
    keeps the first definition rather than an unusable empty enum. Metadata
    from both sides is merged (``_merge_metadata``) so no branch's
    description is dropped.
    """
    existing_values = _collect_const_enum(existing)
    incoming_values = _collect_const_enum(incoming)
    if existing_values and incoming_values:
        incoming_keys = {_json_value_key(value) for value in incoming_values}
        common = [value for value in existing_values if _json_value_key(value) in incoming_keys]
        if common:
            merged = {k: v for k, v in existing.items() if k != "const"}
            merged["enum"] = _dedupe_values(common)
            existing_type = existing.get("type")
            if existing_type is not None and existing_type == incoming.get("type"):
                merged["type"] = existing_type
            merged.update(_merge_metadata(existing, incoming))
            return merged
        return dict(existing)
    if existing_values or incoming_values:
        closed = existing if existing_values else incoming
        merged = dict(closed)
        merged.update(_merge_metadata(existing, incoming))
        return merged
    return dict(existing)

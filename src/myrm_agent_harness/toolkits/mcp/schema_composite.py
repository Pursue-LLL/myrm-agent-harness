"""MCP Schema Composite-Keyword Normalization.

Transforms third-party composite keywords that strict LLM providers reject:
property-level ``anyOf``/``oneOf`` unions of same-typed ``const``s are
collapsed into ``enum`` (closed value sets stay visible), and top-level
``anyOf``/``oneOf``/``allOf`` object branches are flattened into a single
flat ``properties`` set so tools with alternative-argument shapes (e.g.
kimi-cu ``click``: ``index`` *or* ``x``/``y``) remain fully usable.

[INPUT]
- normalized schema dict (after $ref resolution)

[OUTPUT]
- collapse_const_unions: Collapses property-level anyOf/oneOf unions of same-typed consts into enum (lone null branch → nullable, outer metadata preserved).
- flatten_top_level_composite: Merges top-level anyOf/oneOf/allOf object branches into a flat properties set (cross-branch const/enum union, common-required promotion, exclusivity hints).

[POS]
MCP Schema Utilities. Property-level const-union collapsing and
top-level composite flattening for LLM compatibility.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_COMPOSITE_KEYS = ("anyOf", "oneOf", "allOf")

_CONST_PRIMITIVE_TYPES: dict[type, str] = {
    bool: "boolean",
    int: "integer",
    float: "number",
    str: "string",
}


def collapse_const_unions(schema: dict[str, Any]) -> dict[str, Any]:
    """Collapse ``anyOf``/``oneOf`` unions of same-typed consts to ``enum``.

    Rust/TypeScript MCP servers declare closed value sets as const unions —
    e.g. ``{"anyOf": [{"const": "red"}, {"const": "green"}]}``. Strict LLM
    providers reject or strip such unions (``const`` becomes a bare scalar),
    hiding every allowed value from the model; the equivalent ``enum`` form
    is universally supported. Only unions where every non-null branch is a
    pure ``const`` of the same primitive type are collapsed — mixed unions
    and constrained branches pass through untouched, and a single ``null``
    branch is dropped as ``nullable: true``. A node carrying more than one
    composite keyword (e.g. ``anyOf`` alongside ``allOf``) is left alone:
    collapsing one constraint would silently discard the sibling one, and an
    outer ``type`` conflicting with the folded type blocks the collapse.
    Outer metadata (``title``/``description``/``default``) is carried onto the
    replacement, and duplicate const values are deduplicated while keeping
    first-seen order. Recursive, deterministic (branch order preserved),
    idempotent, and the input schema is never mutated.
    """

    def _walk(node: object) -> object:
        if isinstance(node, list):
            return [_walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in ("enum", "const", "default", "examples"):
                # Data positions: literal values, not schemas — an enum array
                # may legally contain objects that must never be rewritten.
                out[key] = value
            else:
                out[key] = _walk(value)
        present = [
            key
            for key in _COMPOSITE_KEYS
            if isinstance(out.get(key), list) and out[key]
        ]
        if present != ["anyOf"] and present != ["oneOf"]:
            return out
        variants = out[present[0]]
        null_branches = [
            item
            for item in variants
            if isinstance(item, dict)
            and item.get("type") == "null"
            and "const" not in item
        ]
        const_branches = [item for item in variants if item not in null_branches]
        if len(null_branches) > 1 or not const_branches:
            return out
        branch_types = {_const_branch_type(item) for item in const_branches}
        if len(branch_types) != 1 or None in branch_types:
            return out
        folded_type = branch_types.pop()
        declared_type = out.get("type")
        if declared_type is not None and declared_type != folded_type:
            return out
        replacement: dict[str, Any] = {
            "type": folded_type,
            "enum": list(dict.fromkeys(item["const"] for item in const_branches)),
        }
        if null_branches:
            replacement["nullable"] = True
        for meta_key in ("title", "description", "default", "examples"):
            if meta_key in out and meta_key not in replacement:
                replacement[meta_key] = out[meta_key]
        return replacement

    result = _walk(schema)
    if not isinstance(result, dict):
        return schema
    return result


def _const_branch_type(branch: object) -> str | None:
    """Return the JSON-Schema primitive type of a pure ``const`` branch.

    A branch qualifies when it is a dict carrying ``const`` with a primitive
    value and no constraining keyword other than ``type``/``title``/
    ``description``; any declared ``type`` must match the value's type.
    ``bool`` is checked before ``int`` (its subclass) so True/False never
    classify as integers. Returns ``None`` otherwise.
    """
    if not isinstance(branch, dict) or "const" not in branch:
        return None
    extra = set(branch) - {"const", "type", "title", "description"}
    if extra:
        return None
    value = branch["const"]
    for py_type, json_type in _CONST_PRIMITIVE_TYPES.items():
        if type(value) is py_type:
            declared = branch.get("type")
            if declared is not None and declared != json_type:
                return None
            return json_type
    return None


_MAX_COMPOSITE_FLATTEN_DEPTH = 5


def flatten_top_level_composite(schema: dict[str, Any]) -> dict[str, Any]:
    """Flatten top-level ``anyOf``/``oneOf``/``allOf`` object branches.

    Third-party MCP servers sometimes declare a tool's parameters with a
    top-level composite keyword — e.g. kimi-cu ``click`` accepts ``index``
    *or* ``x``/``y``. Strict providers reject top-level combinators, and the
    LLM-facing schema (the dict passed to ``StructuredTool.args_schema``)
    only carries parameter meaning via ``properties``, so such tools silently
    lose every parameter. Merging each object branch's ``properties`` into a
    single flat set makes the tool usable; the original alternative constraint
    is folded into ``description`` so the LLM picks one valid combination.

    ``allOf`` branches are conjunctive — their ``required`` lists are merged.
    ``anyOf``/``oneOf`` branches are alternative: a property redefined across
    branches keeps the union of its ``const``/``enum`` values (so a
    discriminator field like ``type`` exposes every operational mode instead
    of silently keeping only the last branch's value), and a property that is
    required by *every* branch is promoted to the top-level ``required``.
    When a ``const``/``enum`` branch is unioned with an open type (e.g. bare
    ``{"type": "string"}``) the merged schema widens to the open type — its
    domain already covers the closed set, so keeping ``const``/``enum`` would
    wrongly hide legal values. The remaining per-branch alternatives are
    spelled out in ``description`` as mutually exclusive groups — promoted
    common fields are excluded from that hint because they are mandatory, not
    part of the choice.

    Top-level ``properties`` / ``required`` coexist conjunctively with the
    composite keyword and are always preserved.

    Idempotent: a schema without a top-level composite is returned unchanged.
    """
    return _flatten_top_level_composite(schema, depth=0)


def _flatten_top_level_composite(
    schema: dict[str, Any], *, depth: int
) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return schema

    composite: dict[str, list[dict[str, Any]]] = {}
    for key in _COMPOSITE_KEYS:
        branches = schema.get(key)
        if isinstance(branches, list) and branches:
            dict_branches = [b for b in branches if isinstance(b, dict)]
            if dict_branches:
                composite[key] = dict_branches
    if not composite:
        return schema

    merged_props: dict[str, Any] = {}
    merged_required: list[str] = []
    alternative_groups: list[list[str]] = []
    alt_required_counts: dict[str, int] = {}
    alt_branch_count = 0

    # Top-level properties/required apply conjunctively alongside the
    # composite keyword (JSON Schema semantics) — always keep them.
    top_props = schema.get("properties")
    if isinstance(top_props, dict) and top_props:
        merged_props.update(top_props)
    top_required = schema.get("required")
    if isinstance(top_required, list):
        merged_required.extend(top_required)

    for keyword, branches in composite.items():
        for branch in branches:
            resolved = _resolve_composite_branch(branch, depth)
            props = resolved.get("properties")
            if not isinstance(props, dict):
                continue
            if keyword == "allOf":
                for name in props:
                    _merge_branch_property(merged_props, name, props[name])
                req = resolved.get("required")
                if isinstance(req, list):
                    merged_required.extend(req)
            else:
                alt_branch_count += 1
                branch_required = resolved.get("required")
                if isinstance(branch_required, list):
                    for name in branch_required:
                        if isinstance(name, str) and name in props:
                            alt_required_counts[name] = (
                                alt_required_counts.get(name, 0) + 1
                            )
                alternative_groups.append(sorted(props))
                for name in props:
                    _merge_branch_property(merged_props, name, props[name])

    # A property required by every alternative branch (e.g. the ``type``
    # discriminator of a oneOf union) is mandatory no matter which branch is
    # chosen — promote it so the LLM sees it as required instead of optional.
    common_required = {
        name
        for name, count in alt_required_counts.items()
        if alt_branch_count > 1 and count == alt_branch_count
    }
    merged_required.extend(sorted(common_required))

    if not merged_props:
        return schema

    result: dict[str, Any] = {"type": "object", "properties": merged_props}
    for key, value in schema.items():
        if key not in ("anyOf", "oneOf", "allOf", "type", "properties"):
            result[key] = value
    if merged_required:
        result["required"] = list(dict.fromkeys(merged_required))

    # The exclusivity hint lists only the per-branch choices; common required
    # fields are excluded since they are always present, not an alternative.
    exclusive_groups = [
        [name for name in group if name not in common_required]
        for group in alternative_groups
    ]
    constraint = _build_alternative_constraint(exclusive_groups)
    if constraint:
        existing = result.get("description")
        result["description"] = (
            f"{existing} {constraint}".strip() if existing else constraint
        )

    logger.debug(
        "Flattened top-level composite (%s) into %d flat properties",
        "+".join(composite),
        len(merged_props),
    )
    return result


def _resolve_composite_branch(branch: dict[str, Any], depth: int) -> dict[str, Any]:
    """Return a branch schema with any nested combinators flattened."""
    if depth >= _MAX_COMPOSITE_FLATTEN_DEPTH:
        return branch
    for key in _COMPOSITE_KEYS:
        if isinstance(branch.get(key), list):
            return _flatten_top_level_composite(branch, depth=depth + 1)
    return branch


def _build_alternative_constraint(alternatives: list[list[str]]) -> str | None:
    """Build a mutual-exclusivity hint when several non-empty groups exist."""
    non_empty = [alt for alt in alternatives if alt]
    if len(non_empty) < 2:
        return None
    groups = "; ".join(f"({', '.join(alt)})" for alt in non_empty)
    return f"Parameters are mutually exclusive alternatives — provide exactly one group: {groups}."


def _collect_enum_values(prop_schema: dict[str, Any]) -> list[Any]:
    """Return the enumerable values of a property schema (``const`` → singleton)."""
    if "const" in prop_schema:
        return [prop_schema["const"]]
    enum_values = prop_schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return enum_values
    return []


def _dedupe_preserving_order(values: list[Any]) -> list[Any]:
    """Dedupe arbitrary JSON values while preserving first-seen order."""
    seen: set[str] = set()
    unique: list[Any] = []
    for value in values:
        try:
            key = json.dumps(value, sort_keys=True)
        except (TypeError, ValueError):
            key = repr(value)
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def _union_enum_schema(
    first: dict[str, Any],
    second: dict[str, Any],
    first_values: list[Any],
    second_values: list[Any],
) -> dict[str, Any]:
    """Merge two enum-like property definitions into a single union schema.

    Keeps a shared ``type`` (dropped when the branches disagree), unifies
    equal descriptions and concatenates different ones, and emits the
    deduplicated union of both value lists as ``enum``.
    """
    merged: dict[str, Any] = {}
    first_title = first.get("title")
    if first_title or second.get("title"):
        merged["title"] = first_title or second.get("title")
    first_description = first.get("description")
    second_description = second.get("description")
    if first_description and second_description:
        merged["description"] = (
            first_description
            if first_description == second_description
            else f"{first_description} {second_description}"
        )
    elif first_description or second_description:
        merged["description"] = first_description or second_description
    first_default = first.get("default")
    if "default" in first or "default" in second:
        merged["default"] = (
            first_default if "default" in first else second.get("default")
        )
    if "type" in first and first.get("type") == second.get("type"):
        merged["type"] = first["type"]
    merged["enum"] = _dedupe_preserving_order(first_values + second_values)
    return merged


def _merge_open_schema(
    const_side: dict[str, Any], open_side: dict[str, Any]
) -> dict[str, Any]:
    """Merge a closed const/enum schema with an open (unconstrained) one.

    A const/enum definition lists allowed values while an open definition
    (e.g. bare ``{"type": "string"}``) accepts anything of its type. Their
    union is the open type — every closed value is already a member — so the
    result carries the open side's type and drops ``const``/``enum``.
    Metadata (``title``/``description``/``default``) is kept from either
    side, preferring ``const_side`` values already present in ``open_side``.
    """
    merged: dict[str, Any] = {
        key: value
        for key, value in open_side.items()
        if key not in ("const", "enum")
    }
    for meta_key in ("title", "description", "default"):
        if meta_key in const_side and meta_key not in merged:
            merged[meta_key] = const_side[meta_key]
    return merged


def _merge_branch_property(
    merged_props: dict[str, Any], name: str, prop_schema: object
) -> None:
    """Merge one branch property into the flat properties set.

    A property redefined across ``anyOf``/``oneOf`` branches keeps the union
    of its allowed ``const``/``enum`` values — otherwise a discriminator field
    like ``type`` would silently retain only the last branch's value and hide
    every other operational mode from the LLM. When one branch constrains a
    closed set and the other is an open type, the union is the open type
    (every closed value already belongs to it), so ``const``/``enum`` is
    dropped rather than narrowed. Non-enumerable redefinitions keep the first
    occurrence for determinism.
    """
    existing = merged_props.get(name)
    if not isinstance(prop_schema, dict):
        # Malformed third-party schemas may carry a non-object property value;
        # keep the first definition when one exists, else store it verbatim.
        if existing is None:
            merged_props[name] = prop_schema
        return
    if existing is None or not isinstance(existing, dict):
        merged_props[name] = prop_schema
        return
    logger.debug(
        "Top-level composite flatten: property '%s' redefined across branches",
        name,
    )
    first_values = _collect_enum_values(existing)
    second_values = _collect_enum_values(prop_schema)
    if first_values and second_values:
        merged_props[name] = _union_enum_schema(
            existing, prop_schema, first_values, second_values
        )
    elif first_values or second_values:
        # One branch is a closed const/enum set, the other an open type.
        # The union of a closed set with an open domain is the open domain
        # (every const value already belongs to it), so the merged schema
        # must drop const/enum — keeping only the closed value would hide
        # the legal "any value" alternative from the LLM.
        const_side = existing if first_values else prop_schema
        open_side = prop_schema if first_values else existing
        merged_props[name] = _merge_open_schema(const_side, open_side)

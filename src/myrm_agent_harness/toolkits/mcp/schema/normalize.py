"""MCP Schema Normalization.

Prepares a third-party JSON Schema for LLM consumption: cache-stable
canonicalization (deterministic key ordering for prompt prefix cache
stability), inline ``$ref``/``$defs`` resolution, and deep-nesting
flattening to dot-path notation for LLMs that reject nested objects.

[INPUT]
- raw MCP ``inputSchema`` dict

[OUTPUT]
- canonicalize_schema_for_cache: Deterministic key ordering for prompt prefix cache stability.
- flatten_json_schema: Resolves $ref pointers inline securely.
- analyze_schema_complexity: Measures leaf count and max depth.
- flatten_deep_schema: Flattens deeply-nested schemas to dot-path notation.
- nest_flat_arguments: Restores dot-path args to nested structure for dispatch.

[POS]
MCP Schema Utilities. Cache-stable canonicalization, $ref flattening, and
deep-nesting flattening (dot-path) for LLM compatibility.
"""

import logging
from typing import Any, cast

logger = logging.getLogger(__name__)

_SET_LIKE_SCHEMA_KEYS = frozenset({"required", "dependentRequired"})


def canonicalize_schema_for_cache(value: object) -> object:
    """Recursively normalize a JSON schema for prompt prefix cache stability.

    MCP servers may return tool schemas with non-deterministic key ordering
    across restarts. Without canonicalization the serialized schema string
    changes → system prompt prefix differs → prefix cache is invalidated →
    higher TTFT and doubled token cost.

    Rules (mirrors deepseek-reasonix ``canonicalizeSchemaForCache``):
    - Object keys are sorted lexicographically at every nesting level.
    - ``required`` and ``dependentRequired`` arrays (set-like semantics)
      are sorted; other arrays (e.g. ``enum``) preserve insertion order.
    """
    return _canonicalize(value, parent_key=None)


def _canonicalize(value: object, *, parent_key: str | None) -> object:
    if isinstance(value, list):
        mapped = [_canonicalize(item, parent_key=None) for item in value]
        if parent_key in _SET_LIKE_SCHEMA_KEYS and all(_is_scalar(v) for v in mapped):
            return sorted(mapped, key=str)
        return mapped

    if not isinstance(value, dict):
        return value

    if parent_key == "dependentRequired":
        out: dict[str, object] = {}
        for key in sorted(value):
            arr = value[key]
            if isinstance(arr, list) and all(_is_scalar(v) for v in arr):
                out[key] = sorted(arr, key=str)
            else:
                out[key] = _canonicalize(arr, parent_key=key)
        return out

    return {key: _canonicalize(value[key], parent_key=key) for key in sorted(value)}


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _degrade_unresolved_ref(node: dict[str, Any]) -> dict[str, Any]:
    """Replace an unresolvable ``$ref`` node with a permissive schema.

    Drops the ``$ref`` key and keeps sibling metadata plus a declared scalar
    ``type`` when present; otherwise the node becomes a permissive object
    (``additionalProperties: true``) so the LLM can still pass an arbitrary
    value instead of the parameter silently disappearing.  Mirrors the
    outbound ``_degrade_unresolved_ref`` in ``adapters/schema/normalizer.py``.
    """
    declared_type = node.get("type")
    if isinstance(declared_type, str) and declared_type != "object":
        return {key: value for key, value in node.items() if key != "$ref"}
    degraded: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": True,
    }
    for key in ("description", "title", "default", "examples"):
        if key in node and key not in degraded:
            degraded[key] = node[key]
    return degraded


def _lookup_ref_target(
    parts: list[str],
    definitions: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve a ``#/...`` reference path against the definitions container.

    Supports ``#/definitions/X`` / ``#/$defs/X`` and OpenAPI 3.x
    ``#/components/schemas/X``, plus nested descent such as
    ``#/definitions/Foo/properties/bar``.  Returns ``None`` when the path
    cannot be walked.
    """
    if not parts or parts[0] != "#" or len(parts) < 3:
        return None
    start = 0
    if parts[1] in ("definitions", "$defs"):
        start = 2
    elif parts[1] == "components" and len(parts) >= 4 and parts[2] == "schemas":
        start = 3
    else:
        return None
    node: Any = definitions.get(parts[start]) if start < len(parts) else None
    if node is None:
        return None
    for seg in parts[start + 1 :]:
        if isinstance(node, dict) and seg in node:
            node = node[seg]
        else:
            return None
    return node if isinstance(node, dict) else None


def flatten_json_schema(schema: dict[str, Any], max_depth: int = 10) -> dict[str, Any]:
    """Flattens a JSON schema by recursively resolving $ref tags inline.

    This ensures that LLMs which do not support nested definitions can still
    understand and generate appropriate parameters.

    Args:
        schema: The original JSON schema dictionary.
        max_depth: Maximum ``$ref`` reference-chain depth.  Guards against
            circular ``$ref`` definitions recursing forever; ordinary nested
            objects/arrays do not consume this budget, so deeply nested but
            acyclic schemas survive for ``flatten_deep_schema``.

    Returns:
        A new flattened schema dictionary.
    """
    if not isinstance(schema, dict):
        return schema

    definitions = schema.get("definitions") or schema.get("$defs") or {}
    # OpenAPI 3.x gateway servers emit ``#/components/schemas/...`` refs whose
    # definitions live in a ``components`` container on the same document.
    components = schema.get("components")
    if isinstance(components, dict):
        comp_schemas = components.get("schemas")
        if isinstance(comp_schemas, dict):
            if not isinstance(definitions, dict):
                definitions = {}
            definitions = {**comp_schemas, **definitions}

    def resolve(node: Any, ref_depth: int) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_path = node["$ref"]
                target = _lookup_ref_target(ref_path.split("/"), definitions)
                if target is not None:
                    if ref_depth > max_depth:
                        # Reference chain deeper than the safety bound
                        # (likely a circular $ref) — degrade instead of
                        # recursing forever.
                        return _degrade_unresolved_ref(node)
                    # Recursively resolve the definition
                    resolved_node = resolve(target, ref_depth + 1)
                    # Merge any other keys from the node (like description overrides)
                    merged = {**resolved_node}
                    for k, v in node.items():
                        if k != "$ref":
                            merged[k] = resolve(v, ref_depth + 1)
                    return merged
                # Unresolvable ref (missing definition or external URL): degrade
                # instead of leaking the raw pointer — strict providers reject
                # a bare `$ref` with 400, disabling the whole tool.
                return _degrade_unresolved_ref(node)
            # Ordinary nesting does not consume the reference-chain depth — the
            # bound exists only to stop circular $ref recursion, so deeply
            # nested (but acyclic) schemas survive for `flatten_deep_schema`.
            return {k: resolve(v, ref_depth) for k, v in node.items()}
        elif isinstance(node, list):
            return [resolve(item, ref_depth) for item in node]
        else:
            return node

    # Start resolution from the root schema
    flattened = resolve(schema, 0)

    # Remove definitions as they are now fully inlined
    if isinstance(flattened, dict):
        flattened.pop("definitions", None)
        flattened.pop("$defs", None)
        flattened.pop("components", None)

    return cast(dict[str, Any], flattened)


# ---------------------------------------------------------------------------
# Deep-nesting flattening: dot-path notation for LLM compatibility
# ---------------------------------------------------------------------------

_FLATTEN_DEPTH_THRESHOLD = 2
_FLATTEN_LEAF_THRESHOLD = 10


def analyze_schema_complexity(schema: dict[str, Any]) -> tuple[int, int]:
    """Analyze schema complexity by counting leaves and measuring max depth.

    Returns:
        (leaf_count, max_depth) tuple.
    """

    def _walk(node: dict[str, Any], depth: int) -> tuple[int, int]:
        if node.get("type") == "object" and "properties" in node:
            total_leaves = 0
            max_d = depth
            for child in node["properties"].values():
                if isinstance(child, dict):
                    leaves, d = _walk(child, depth + 1)
                    total_leaves += leaves
                    max_d = max(max_d, d)
            return total_leaves, max_d
        return 1, depth

    if not isinstance(schema, dict):
        return 0, 0
    return _walk(schema, 0)


class FlattenMeta:
    """Metadata from a flatten operation, used to restore nested structure."""

    __slots__ = ("original_required", "was_flattened")

    def __init__(
        self, was_flattened: bool, original_required: list[str] | None = None
    ) -> None:
        self.was_flattened = was_flattened
        self.original_required = original_required


def flatten_deep_schema(
    schema: dict[str, Any],
    depth_threshold: int = _FLATTEN_DEPTH_THRESHOLD,
    leaf_threshold: int = _FLATTEN_LEAF_THRESHOLD,
) -> tuple[dict[str, Any], FlattenMeta]:
    """Flatten deeply-nested object schemas to dot-path notation.

    Triggered when leaf_count > leaf_threshold OR max_depth > depth_threshold.
    Non-object leaves (arrays, primitives, anyOf/oneOf) are kept as-is.

    Args:
        schema: JSON schema dict (after $ref resolution).
        depth_threshold: Max nesting depth before flattening.
        leaf_threshold: Max leaf count before flattening.

    Returns:
        (flattened_schema, FlattenMeta) tuple.
    """
    leaf_count, max_depth = analyze_schema_complexity(schema)

    if leaf_count <= leaf_threshold and max_depth <= depth_threshold:
        return schema, FlattenMeta(was_flattened=False)

    flat_props: dict[str, dict[str, Any]] = {}
    flat_required: list[str] = []

    def _collect(
        prefix: str,
        node: dict[str, Any],
        parent_required: bool,
    ) -> None:
        if node.get("type") == "object" and "properties" in node:
            required_set = set(node.get("required", []))
            for key, child in node["properties"].items():
                if not isinstance(child, dict):
                    continue
                next_prefix = f"{prefix}.{key}" if prefix else key
                child_required = parent_required and key in required_set
                _collect(next_prefix, child, child_required)
            return
        # Leaf node: store with dot-path key
        flat_props[prefix] = node
        if parent_required:
            flat_required.append(prefix)

    _collect("", schema, True)

    # Check for naming conflicts (extremely rare but handle gracefully)
    if not flat_props:
        return schema, FlattenMeta(was_flattened=False)

    flattened_schema: dict[str, Any] = {
        "type": "object",
        "properties": flat_props,
    }
    if flat_required:
        flattened_schema["required"] = flat_required

    logger.debug(
        "Flattened deep schema: %d leaves, depth %d -> %d flat properties",
        leaf_count,
        max_depth,
        len(flat_props),
    )

    return flattened_schema, FlattenMeta(
        was_flattened=True,
        original_required=schema.get("required"),
    )


def has_dot_keys(args: dict[str, Any]) -> bool:
    """Check if any argument key uses dot-notation (flattened format)."""
    return any("." in key for key in args)


def nest_flat_arguments(flat_args: dict[str, Any]) -> dict[str, Any]:
    """Restore dot-path arguments to nested structure for MCP dispatch.

    Only processes keys containing dots; pass-through keys without dots are kept as-is.
    """
    result: dict[str, Any] = {}
    for key, value in flat_args.items():
        if "." not in key:
            result[key] = value
            continue
        parts = key.split(".")
        cur = result
        for part in parts[:-1]:
            if part not in cur or not isinstance(cur[part], dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value
    return result

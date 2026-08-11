"""MCP Schema Utilities.

Provides schema sanitization, $ref flattening, cache-stable canonicalization,
deep-nesting flattening, and dynamic type coercion to ensure compatibility
with various LLMs.

[INPUT]
- None

[OUTPUT]
- canonicalize_schema_for_cache: Deterministic key ordering for prompt prefix cache stability.
- flatten_json_schema: Resolves $ref pointers inline securely.
- collapse_const_unions: Collapses property-level anyOf/oneOf unions of same-typed consts into enum (lone null branch → nullable, outer metadata preserved).
- flatten_top_level_composite: Merges top-level anyOf/oneOf/allOf object branches into a flat properties set (cross-branch const/enum union, common-required promotion, exclusivity hints).
- analyze_schema_complexity: Measures leaf count and max depth.
- flatten_deep_schema: Flattens deeply-nested schemas to dot-path notation.
- nest_flat_arguments: Restores dot-path args to nested structure for dispatch.
- coerce_arguments_by_schema: Corrects parsed arguments, handles mixed-union container literals, and completes required nullable omissions.
- prepare_mcp_call_arguments: Strip null optional fields before MCP call_tool (strict JSON Schema hosts).
- get_schema_coercion_stats/reset_schema_coercion_stats: Lightweight runtime coercion counters.

[POS]
MCP Schema Utilities. Provides schema sanitization, $ref flattening,
cache-stable canonicalization, deep-nesting flattening (dot-path),
top-level composite flattening, dynamic type coercion, strict-host
nullable completion, mixed-union safe container coercion,
and coercion observability counters.
"""

import ast
import contextlib
import json
import logging
import re
from typing import Any, cast

logger = logging.getLogger(__name__)


_SET_LIKE_SCHEMA_KEYS = frozenset({"required", "dependentRequired"})
_SCHEMA_COERCION_STAT_KEYS = (
    "coerce_argument_calls",
    "null_string_to_none",
    "required_nullable_null_injections",
    "json_container_coercions",
    "json_type_guard_rejections",
    "ast_container_coercions",
    "ast_type_guard_rejections",
)
_SCHEMA_COERCION_STATS: dict[str, int] = {key: 0 for key in _SCHEMA_COERCION_STAT_KEYS}


def _bump_schema_coercion_stat(key: str) -> None:
    if key in _SCHEMA_COERCION_STATS:
        _SCHEMA_COERCION_STATS[key] += 1


def get_schema_coercion_stats() -> dict[str, int]:
    """Return a snapshot of best-effort schema coercion counters."""
    return dict(_SCHEMA_COERCION_STATS)


def reset_schema_coercion_stats() -> None:
    """Reset schema coercion counters (useful for deterministic tests)."""
    for key in _SCHEMA_COERCION_STATS:
        _SCHEMA_COERCION_STATS[key] = 0


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


def flatten_json_schema(schema: dict[str, Any], max_depth: int = 10) -> dict[str, Any]:
    """Flattens a JSON schema by recursively resolving $ref tags inline.

    This ensures that LLMs which do not support nested definitions can still
    understand and generate appropriate parameters.

    Args:
        schema: The original JSON schema dictionary.
        max_depth: Maximum recursion depth to prevent infinite loops.

    Returns:
        A new flattened schema dictionary.
    """
    if not isinstance(schema, dict):
        return schema

    definitions = schema.get("definitions", {}) or schema.get("$defs", {})

    def resolve(node: Any, depth: int) -> Any:
        if depth > max_depth and isinstance(node, (dict, list)):
            # Fallback to empty dict if we hit max depth to prevent infinite recursion
            return {}

        if isinstance(node, dict):
            if "$ref" in node:
                ref_path = node["$ref"]
                # Parse local ref like #/definitions/MyType
                parts = ref_path.split("/")
                if (
                    len(parts) >= 3
                    and parts[0] == "#"
                    and parts[1] in ("definitions", "$defs")
                ):
                    def_name = parts[2]
                    if def_name in definitions:
                        # Recursively resolve the definition
                        resolved_node = resolve(definitions[def_name], depth + 1)
                        # Merge any other keys from the node (like description overrides)
                        merged = {**resolved_node}
                        for k, v in node.items():
                            if k != "$ref":
                                merged[k] = resolve(v, depth + 1)
                        return merged
            return {k: resolve(v, depth + 1) for k, v in node.items()}
        elif isinstance(node, list):
            return [resolve(item, depth + 1) for item in node]
        else:
            return node

    # Start resolution from the root schema
    flattened = resolve(schema, 0)

    # Remove definitions as they are now fully inlined
    if isinstance(flattened, dict):
        flattened.pop("definitions", None)
        flattened.pop("$defs", None)

    return cast(dict[str, Any], flattened)


def _strip_markdown_json(value: str) -> str:
    """Safely strip markdown code block backticks if present."""
    value = value.strip()
    if value.startswith("```"):
        # Match ```json\n ... \n``` or just ``` ... ```
        match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", value, re.DOTALL)
        if match:
            return match.group(1).strip()
    return value


def _looks_like_json_container_literal(value: str) -> bool:
    """Heuristic: looks like a JSON object/array literal."""
    stripped = value.strip()
    if len(stripped) < 2:
        return False
    return (stripped[0] == "{" and stripped[-1] == "}") or (
        stripped[0] == "[" and stripped[-1] == "]"
    )


def _extract_schema_types(schema: dict[str, Any]) -> list[str]:
    """Collect declared JSON schema types from direct and union forms."""
    collected: list[str] = []

    def _append_types(raw_type: Any) -> None:
        if isinstance(raw_type, str):
            if raw_type not in collected:
                collected.append(raw_type)
            return
        if isinstance(raw_type, list):
            for item in raw_type:
                if isinstance(item, str) and item not in collected:
                    collected.append(item)

    _append_types(schema.get("type"))
    for union_key in ("anyOf", "oneOf"):
        variants = schema.get(union_key)
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if isinstance(variant, dict):
                _append_types(variant.get("type"))

    return collected


def _schema_declares_null_literal(schema: dict[str, Any]) -> bool:
    """Return True when a single schema node explicitly allows a null literal."""
    if schema.get("nullable") is True:
        return True
    if "const" in schema and schema["const"] is None:
        return True
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and any(item is None for item in enum_values):
        return True
    return "null" in _extract_schema_types(schema)


def _schema_allows_null(schema: dict[str, Any]) -> bool:
    """Return True when the schema explicitly permits null."""
    if _schema_declares_null_literal(schema):
        return True
    for union_key in ("anyOf", "oneOf"):
        variants = schema.get(union_key)
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if isinstance(variant, dict) and _schema_declares_null_literal(variant):
                return True
    return False


def prepare_mcp_call_arguments(
    kwargs: dict[str, object],
    args_schema: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Prepare kwargs for MCP ``call_tool``.

    StructuredTool/Pydantic validation may expand omitted optional fields to
    explicit ``None``. Strict MCP servers (e.g. 12306) reject ``null`` for
    typed optional properties that define non-null defaults — those keys must
    be omitted instead.

    Preserves explicit ``None`` only for required properties whose schema
    allows null (strict-host nullable completion from coercion).
    """
    if not kwargs:
        return kwargs

    properties: dict[str, Any] = {}
    required: set[str] = set()
    if isinstance(args_schema, dict):
        raw_props = args_schema.get("properties")
        if isinstance(raw_props, dict):
            properties = raw_props
        raw_required = args_schema.get("required")
        if isinstance(raw_required, list):
            required = {key for key in raw_required if isinstance(key, str)}

    prepared: dict[str, object] = {}
    for key, value in kwargs.items():
        if value is not None:
            prepared[key] = value
            continue
        prop_schema = properties.get(key)
        if (
            key in required
            and isinstance(prop_schema, dict)
            and _schema_allows_null(prop_schema)
        ):
            prepared[key] = None
    return prepared


def _primary_non_null_type(schema: dict[str, Any]) -> str | None:
    """Pick the first non-null declared type for coercion decisions."""
    for schema_type in _extract_schema_types(schema):
        if schema_type != "null":
            return schema_type
    return None


def _schema_expects_type(schema: dict[str, Any], expected_type: str) -> bool:
    """Return True when schema accepts the given type."""
    return expected_type in _extract_schema_types(schema)


def _value_conforms_to_schema_types(schema: dict[str, Any], value: Any) -> bool:
    """Return True when runtime value already matches one allowed schema type."""
    if value is None:
        return _schema_allows_null(schema)
    if isinstance(value, bool):
        return _schema_expects_type(schema, "boolean")
    if isinstance(value, dict):
        return _schema_expects_type(schema, "object")
    if isinstance(value, list):
        return _schema_expects_type(schema, "array")
    if isinstance(value, int):
        return _schema_expects_type(schema, "integer") or _schema_expects_type(
            schema, "number"
        )
    if isinstance(value, float):
        return _schema_expects_type(schema, "number")
    if isinstance(value, str):
        return _schema_expects_type(schema, "string")
    return False


def coerce_value(schema: dict[str, Any], value: Any) -> Any:
    """Recursively coerces a value based on the JSON schema definition."""
    if not isinstance(schema, dict):
        return value

    expected_type = _primary_non_null_type(schema)
    allows_null = _schema_allows_null(schema)

    # If we got a string but expected something else (LLM hallucination)
    if isinstance(value, str):
        clean_value = _strip_markdown_json(value)

        if allows_null and clean_value.lower() == "null":
            _bump_schema_coercion_stat("null_string_to_none")
            return None

        expects_object = _schema_expects_type(schema, "object")
        expects_array = _schema_expects_type(schema, "array")
        should_attempt_container_parse = False
        if expects_object or expects_array:
            should_attempt_container_parse = expected_type in (
                "array",
                "object",
            ) or _looks_like_json_container_literal(clean_value)

        if should_attempt_container_parse:
            try:
                coerced_value = json.loads(clean_value)
                if expects_array and isinstance(coerced_value, list):
                    value = coerced_value
                    _bump_schema_coercion_stat("json_container_coercions")
                    logger.debug("Coerced from string to list via JSON")
                elif expects_object and isinstance(coerced_value, dict):
                    value = coerced_value
                    _bump_schema_coercion_stat("json_container_coercions")
                    logger.debug("Coerced from string to dict via JSON")
                else:
                    _bump_schema_coercion_stat("json_type_guard_rejections")
                    logger.debug(
                        "Rejected JSON coercion for schema (expects object=%s array=%s): got %s",
                        expects_object,
                        expects_array,
                        type(coerced_value).__name__,
                    )
            except json.JSONDecodeError:
                try:
                    coerced_value = ast.literal_eval(clean_value)
                    if expects_array and isinstance(coerced_value, list):
                        value = coerced_value
                        _bump_schema_coercion_stat("ast_container_coercions")
                        logger.debug("Coerced from string to list via AST")
                    elif expects_object and isinstance(coerced_value, dict):
                        value = coerced_value
                        _bump_schema_coercion_stat("ast_container_coercions")
                        logger.debug("Coerced from string to dict via AST")
                    else:
                        _bump_schema_coercion_stat("ast_type_guard_rejections")
                        logger.debug(
                            "Rejected AST coercion for schema (expects object=%s array=%s): got %s",
                            expects_object,
                            expects_array,
                            type(coerced_value).__name__,
                        )
                except (ValueError, SyntaxError):
                    pass
        elif expected_type == "boolean":
            lower_val = clean_value.lower()
            if lower_val == "true":
                value = True
            elif lower_val == "false":
                value = False
        elif expected_type in ("integer", "number"):
            with contextlib.suppress(ValueError):
                value = (
                    int(clean_value)
                    if expected_type == "integer"
                    else float(clean_value)
                )

    # Reverse: got a non-string but expected string (e.g. LLM passed dict for station name)
    if (
        expected_type == "string"
        and not isinstance(value, str)
        and not _value_conforms_to_schema_types(schema, value)
    ):
        if isinstance(value, dict):
            for text_key in ("name", "value", "text", "id"):
                if text_key in value and isinstance(value[text_key], str):
                    logger.debug("Coerced dict to string via key '%s'", text_key)
                    value = value[text_key]
                    break
            else:
                value = json.dumps(value, ensure_ascii=False)
                logger.debug("Coerced dict to string via JSON serialization")
        elif isinstance(value, (int, float, bool)):
            value = str(value)
        elif isinstance(value, list):
            value = json.dumps(value, ensure_ascii=False)

    # Recursive descent for objects
    if _schema_expects_type(schema, "object") and isinstance(value, dict):
        properties = schema.get("properties", {})
        coerced_dict = {}
        for k, v in value.items():
            if k in properties:
                coerced_dict[k] = coerce_value(properties[k], v)
            else:
                coerced_dict[k] = v
        return coerced_dict

    # Recursive descent for arrays
    if _schema_expects_type(schema, "array") and isinstance(value, list):
        items_schema = schema.get("items", {})
        if items_schema:
            return [coerce_value(items_schema, item) for item in value]

    return value


def coerce_arguments_by_schema(
    args_schema: dict[str, Any] | None, kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Coerces argument types based on the schema requirements.

    If the schema expects an array, object, boolean, or number, but the LLM provided a string,
    this attempts to safely parse the string into the expected type. Also strips markdown code blocks.
    Recursively descends into objects and arrays to heal nested hallucinations.
    For strict hosts, fills missing required fields with explicit ``None`` only
    when the corresponding property schema allows ``null``.
    """
    if not args_schema or not isinstance(args_schema, dict):
        return kwargs

    _bump_schema_coercion_stat("coerce_argument_calls")

    properties = args_schema.get("properties", {})
    if not properties:
        return kwargs

    coerced_kwargs = {}
    for key, value in kwargs.items():
        if key in properties:
            coerced_kwargs[key] = coerce_value(properties[key], value)
        else:
            coerced_kwargs[key] = value

    required_keys = args_schema.get("required", [])
    if isinstance(required_keys, list):
        for required_key in required_keys:
            if not isinstance(required_key, str) or required_key in coerced_kwargs:
                continue
            prop_schema = properties.get(required_key)
            if isinstance(prop_schema, dict) and _schema_allows_null(prop_schema):
                # Strict hosts (e.g. Unreal MCP) may require explicit null
                # for missing required+nullable optional fields.
                coerced_kwargs[required_key] = None
                _bump_schema_coercion_stat("required_nullable_null_injections")

    return coerced_kwargs


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


# ---------------------------------------------------------------------------
# Top-level composite flattening: anyOf/oneOf/allOf object branches
# ---------------------------------------------------------------------------

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
    branch is dropped as ``nullable: true``. Outer-node metadata
    (``title``/``description``/``default``) is carried onto the replacement.
    Recursive, deterministic (branch order preserved), idempotent, and the
    input schema is never mutated.
    """

    def _walk(node: object) -> object:
        if isinstance(node, list):
            return [_walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        out: dict[str, Any] = {key: _walk(value) for key, value in node.items()}
        for key in ("anyOf", "oneOf"):
            variants = out.get(key)
            if not isinstance(variants, list) or not variants:
                continue
            null_branches = [
                item
                for item in variants
                if isinstance(item, dict)
                and item.get("type") == "null"
                and "const" not in item
            ]
            const_branches = [item for item in variants if item not in null_branches]
            if len(null_branches) > 1 or not const_branches:
                continue
            branch_types = {_const_branch_type(item) for item in const_branches}
            if len(branch_types) != 1 or None in branch_types:
                continue
            replacement: dict[str, Any] = {
                "type": branch_types.pop(),
                "enum": [item["const"] for item in const_branches],
            }
            if null_branches:
                replacement["nullable"] = True
            for meta_key in ("title", "description", "default"):
                if meta_key in out and meta_key not in replacement:
                    replacement[meta_key] = out[meta_key]
            return replacement
        return out

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
    The remaining per-branch alternatives are spelled out in ``description``
    as mutually exclusive groups — promoted common fields are excluded from
    that hint because they are mandatory, not part of the choice.

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
    if "type" in first and first.get("type") == second.get("type"):
        merged["type"] = first["type"]
    merged["enum"] = _dedupe_preserving_order(first_values + second_values)
    return merged


def _merge_branch_property(
    merged_props: dict[str, Any], name: str, prop_schema: object
) -> None:
    """Merge one branch property into the flat properties set.

    A property redefined across ``anyOf``/``oneOf`` branches keeps the union
    of its allowed ``const``/``enum`` values — otherwise a discriminator field
    like ``type`` would silently retain only the last branch's value and hide
    every other operational mode from the LLM. Non-enumerable redefinitions
    keep the first occurrence for determinism.
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

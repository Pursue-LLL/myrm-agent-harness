"""MCP Schema Utilities.

Provides schema sanitization, $ref flattening, cache-stable canonicalization,
deep-nesting flattening, and dynamic type coercion to ensure compatibility
with various LLMs.

[INPUT]
- None

[OUTPUT]
- canonicalize_schema_for_cache: Deterministic key ordering for prompt prefix cache stability.
- flatten_json_schema: Resolves $ref pointers inline securely.
- analyze_schema_complexity: Measures leaf count and max depth.
- flatten_deep_schema: Flattens deeply-nested schemas to dot-path notation.
- nest_flat_arguments: Restores dot-path args to nested structure for dispatch.
- coerce_arguments_by_schema: Corrects parsed arguments based on schema type.

[POS]
MCP Schema Utilities. Provides schema sanitization, $ref flattening,
cache-stable canonicalization, deep-nesting flattening (dot-path),
and dynamic type coercion.
"""

import ast
import contextlib
import json
import logging
import re
from typing import Any

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
                if len(parts) >= 3 and parts[0] == "#" and parts[1] in ("definitions", "$defs"):
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

    return flattened


def _strip_markdown_json(value: str) -> str:
    """Safely strip markdown code block backticks if present."""
    value = value.strip()
    if value.startswith("```"):
        # Match ```json\n ... \n``` or just ``` ... ```
        match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", value, re.DOTALL)
        if match:
            return match.group(1).strip()
    return value


def coerce_value(schema: dict[str, Any], value: Any) -> Any:
    """Recursively coerces a value based on the JSON schema definition."""
    if not isinstance(schema, dict):
        return value

    expected_type = schema.get("type")

    # If we got a string but expected something else (LLM hallucination)
    if isinstance(value, str) and expected_type != "string":
        clean_value = _strip_markdown_json(value)

        if expected_type in ("array", "object"):
            try:
                coerced_value = json.loads(clean_value)
                value = coerced_value
                logger.debug(f"Coerced from string to {type(coerced_value).__name__} via JSON")
            except json.JSONDecodeError:
                try:
                    coerced_value = ast.literal_eval(clean_value)
                    if isinstance(coerced_value, (list, dict)):
                        value = coerced_value
                        logger.debug(f"Coerced from string to {type(coerced_value).__name__} via AST")
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
                value = int(clean_value) if expected_type == "integer" else float(clean_value)

    # Reverse: got a non-string but expected string (e.g. LLM passed dict for station name)
    if expected_type == "string" and not isinstance(value, str):
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
    if expected_type == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        coerced_dict = {}
        for k, v in value.items():
            if k in properties:
                coerced_dict[k] = coerce_value(properties[k], v)
            else:
                coerced_dict[k] = v
        return coerced_dict

    # Recursive descent for arrays
    if expected_type == "array" and isinstance(value, list):
        items_schema = schema.get("items", {})
        if items_schema:
            return [coerce_value(items_schema, item) for item in value]

    return value


def coerce_arguments_by_schema(args_schema: dict[str, Any] | None, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Coerces argument types based on the schema requirements.

    If the schema expects an array, object, boolean, or number, but the LLM provided a string,
    this attempts to safely parse the string into the expected type. Also strips markdown code blocks.
    Recursively descends into objects and arrays to heal nested hallucinations.
    """
    if not args_schema or not isinstance(args_schema, dict):
        return kwargs

    properties = args_schema.get("properties", {})
    if not properties:
        return kwargs

    coerced_kwargs = {}
    for key, value in kwargs.items():
        if key in properties:
            coerced_kwargs[key] = coerce_value(properties[key], value)
        else:
            coerced_kwargs[key] = value

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

    def __init__(self, was_flattened: bool, original_required: list[str] | None = None) -> None:
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

"""Deterministic property-key sanitization for MCP tool schemas.

Anthropic (and Bedrock/Vertex/Azure fronting it) reject tool input schemas
whose property keys do not match its allowed key pattern — a single bad key
anywhere in the tools array fails the whole request with HTTP 400.
Cloudflare's flat API MCP ships keys like ``issue_class~neq`` and
``meta.<field>[<operator>]`` that violate this.

This module renames non-conforming property keys to the conforming pattern
``^[a-zA-Z0-9_-]{1,64}$`` deterministically (stable across runs → stable
schema serialization → the prompt prefix cache is preserved) and exposes the
reverse map used at dispatch time to restore the original wire names before
the MCP call.

Note the dot character is intentionally excluded from the allowed set: the
deep-nesting flattener uses ``.`` as its dot-path separator, so allowing a
dot here would make ``nest_flat_arguments`` split legitimate key names.
Renaming ``meta.field`` to ``meta_field`` (and restoring before the call) is
safe and unambiguous.

[INPUT]
- raw MCP ``inputSchema`` dicts (third-party JSON Schema)

[OUTPUT]
- sanitize_property_keys: Rename non-conforming property keys (deterministic, collision-safe).
- restore_property_keys: Reverse the rename so original wire names reach the MCP call.
- sanitize_property_key: Single-key sanitizer (used by renames and tests).

[POS]
MCP Schema Utilities. Deterministic property-key sanitization for provider
compatibility, with dispatch-time restoration of original wire names.
"""

from __future__ import annotations

import re
from typing import Any

_PROPERTY_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_BAD_CHAR_RE = re.compile(r"[^a-zA-Z0-9_-]")
_MAX_PROPERTY_KEY_LEN = 64


def sanitize_property_key(key: str) -> str:
    """Map an arbitrary property key to a conforming one."""
    new = _BAD_CHAR_RE.sub("_", key)[:_MAX_PROPERTY_KEY_LEN].strip("_")
    return new or "param"


def sanitize_property_keys(
    schema: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Rename non-conforming property keys in *schema* (in place when needed).

    Returns ``(new_schema, restore_map)`` where ``restore_map`` maps each
    renamed key back to its original wire name (``{renamed: original}``).
    ``required`` arrays are remapped in lockstep; nested ``properties``,
    ``items``, ``additionalProperties`` and composite branches are handled
    recursively.  When no key needs renaming the original object passes
    through untouched (identity preserved).  Collisions are deduped
    deterministically with numeric suffixes.
    """
    restore_map: dict[str, str] = {}

    def _walk(node: object) -> object:
        if isinstance(node, list):
            return [_walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        props = node.get("properties")
        if isinstance(props, dict):
            renames = _compute_renames(props)
            new_props: dict[str, object] = {}
            for key, value in props.items():
                renamed = renames.get(key, key)
                new_props[renamed] = _walk(value)
                if key != renamed:
                    restore_map[renamed] = key
            if renames:
                node["properties"] = new_props
                required = node.get("required")
                if isinstance(required, list):
                    node["required"] = [
                        renames.get(item, item)
                        for item in required
                        if isinstance(item, str)
                    ]
        for key, value in node.items():
            if key != "properties":
                node[key] = _walk(value)
        return node

    return _walk(schema), restore_map  # type: ignore[return-value]


def _compute_renames(props: dict[str, object]) -> dict[str, str]:
    """Return ``{original: renamed}`` for non-conforming property keys."""
    renames: dict[str, str] = {}
    taken = {key for key in props if _PROPERTY_KEY_RE.match(key)}
    for key in props:
        if _PROPERTY_KEY_RE.match(key):
            continue
        base = sanitize_property_key(key)
        candidate, i = base, 2
        while candidate in taken:
            suffix = f"_{i}"
            candidate = base[: _MAX_PROPERTY_KEY_LEN - len(suffix)] + suffix
            i += 1
        taken.add(candidate)
        renames[key] = candidate
    return renames


def restore_property_keys(
    args: dict[str, Any],
    restore_map: dict[str, str],
) -> dict[str, Any]:
    """Restore renamed property keys in model-emitted *args* to wire names.

    Recurses into nested object values and list items so renamed keys deep in
    the argument tree are restored too; keys absent from the map pass through
    untouched.
    """
    if not restore_map:
        return args

    def _restore_value(value: object) -> object:
        if isinstance(value, dict):
            return {
                restore_map.get(k, k): _restore_value(v) for k, v in value.items()
            }
        if isinstance(value, list):
            return [_restore_value(item) for item in value]
        return value

    return {restore_map.get(k, k): _restore_value(v) for k, v in args.items()}

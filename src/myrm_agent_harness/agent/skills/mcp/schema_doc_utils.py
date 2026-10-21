"""JSON Schema documentation utilities for MCP tool documentation.

[INPUT]
- JSON Schema parameter definitions from MCP tool schemas.

[OUTPUT]
- extract_schema_constraints: Formats JSON Schema constraints as markdown documentation lines.
- build_params_section: Builds full parameters documentation section from JSON Schema.
- build_call_example: Generates minimal call example string from required parameters.
- render_signature / render_type / render_constraint: Compact one-line signatures for L2.
- TOOL_DOC_TEMPLATE: Template for single tool documentation (Level 3).

[POS]
Extracts and renders JSON Schema constraint fields (pattern, enum, default, format, min/max, etc.)
into human-readable markdown, enabling Agent LLMs to generate correct MCP tool arguments on first try.
"""

from __future__ import annotations

import re
from typing import Any

type JsonDict = dict[str, Any]


TOOL_DOC_TEMPLATE = """# {tool_name}

## Description

{tool_desc}

{params_section}

## Returns

Returns a **parsed Python object** (dict, list, str, int, etc.), NOT a JSON string.
Do NOT call `json.loads()` on the result. Only access fields explicitly documented above;
if the return structure is not specified, print it as `[OBSERVATION]` first and continue in a later call.

## Import & Call Example

```python
from skills.{skill_name} import {tool_name}

result = await {tool_name}({call_example})
print(result)
```
"""

# JSON Schema constraint keys that Agent needs for correct parameter formatting.
_CONSTRAINT_RENDERERS: list[tuple[str, str]] = [
    ("pattern", "Pattern (regex)"),
    ("format", "Format"),
    ("default", "Default"),
    ("minimum", "Minimum"),
    ("maximum", "Maximum"),
    ("exclusiveMinimum", "Exclusive minimum"),
    ("exclusiveMaximum", "Exclusive maximum"),
    ("minLength", "Min length"),
    ("maxLength", "Max length"),
    ("minItems", "Min items"),
    ("maxItems", "Max items"),
]


def build_params_section(input_schema: JsonDict) -> str:
    """Build parameters documentation section with full JSON Schema constraints.

    Third-party servers send malformed schemas (``properties`` as a list, ``required``
    as a bare string); documenting them must never raise, because this runs on the
    Level-3 read path the model triggers mid-task.
    """
    properties = input_schema.get("properties") if isinstance(input_schema, dict) else None
    if not isinstance(properties, dict) or not properties:
        return "## Parameters\n\nNo parameters required."

    required = input_schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()

    lines = ["## Parameters\n"]
    for param_name, param_info in properties.items():
        if not isinstance(param_info, dict):
            continue
        param_type = render_type(param_info)
        param_desc = param_info.get("description", "No description")
        is_required = param_name in required_names

        required_tag = " **(required)**" if is_required else " (optional)"
        lines.append(f"### {param_name}{required_tag}")
        lines.append(f"- **Type**: `{param_type}`")
        lines.append(f"- **Description**: {param_desc}")

        constraint_lines = extract_schema_constraints(param_info)
        lines.extend(constraint_lines)

        lines.append("")

    return "\n".join(lines)


def extract_schema_constraints(param_info: JsonDict) -> list[str]:
    """Extract JSON Schema constraint fields as documentation lines.

    Handles: pattern, enum, default, format, min/max, length, items, examples.
    """
    lines: list[str] = []

    for key, label in _CONSTRAINT_RENDERERS:
        value = param_info.get(key)
        if value is not None:
            lines.append(f"- **{label}**: `{value}`")

    enum_values = param_info.get("enum")
    if enum_values and isinstance(enum_values, list):
        formatted = ", ".join(f"`{v}`" for v in enum_values)
        lines.append(f"- **Allowed values**: {formatted}")

    examples = param_info.get("examples")
    if examples and isinstance(examples, list):
        formatted = ", ".join(f"`{v}`" for v in examples[:5])
        lines.append(f"- **Examples**: {formatted}")

    items = param_info.get("items")
    if isinstance(items, dict):
        item_type = items.get("type", "any")
        item_enum = items.get("enum")
        if item_enum and isinstance(item_enum, list):
            formatted = ", ".join(f"`{v}`" for v in item_enum)
            lines.append(f"- **Item type**: `{item_type}` (allowed: {formatted})")
        else:
            lines.append(f"- **Item type**: `{item_type}`")

    return lines


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _render_value(info: JsonDict, ptype: str) -> str:
    """Render a placeholder value for a parameter in a call example."""
    example = info.get("examples", [None])[0] if info.get("examples") else None
    if example is not None:
        return f'"{example}"' if ptype == "string" else str(example)
    if ptype == "string":
        return '"..."'
    if ptype in ("integer", "number"):
        return "0"
    if ptype == "boolean":
        return "True"
    return "..."


def build_call_example(input_schema: JsonDict) -> str:
    """Build a minimal call example string from required parameters.

    Flattened schemas use dot-path names (``config.timeout``) which are not valid
    Python keywords, so those examples switch to a ``**{...}`` dict splat; emitting
    ``config.timeout=...`` directly would be a SyntaxError the model would copy.

    A malformed ``properties``/``required`` from a third-party server yields an empty
    example instead of raising on the Level-3 read path.
    """
    properties = input_schema.get("properties") if isinstance(input_schema, dict) else None
    if not isinstance(properties, dict) or not properties:
        return ""

    required = input_schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()

    names: list[str] = []
    values: list[str] = []
    for name, info in properties.items():
        if name not in required_names or not isinstance(info, dict):
            continue
        ptype = render_type(info)
        names.append(name)
        values.append(_render_value(info, ptype))

    if not names:
        return ""
    if all(_IDENTIFIER.match(name) for name in names):
        return ", ".join(f"{name}={value}" for name, value in zip(names, values, strict=True))
    pairs = ", ".join(f'"{name}": {value}' for name, value in zip(names, values, strict=True))
    return f"**{{{pairs}}}"


def normalize_input_schema(raw: object) -> JsonDict:
    """Normalize MCP tool inputSchema (dict or Pydantic model) to JSON Schema dict."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    model_json_schema = getattr(raw, "model_json_schema", None)
    if callable(model_json_schema):
        result = model_json_schema()
        if isinstance(result, dict):
            return result
    return {}


# --- Compact signatures (SKILL.md / L2) -------------------------------------------------

ENUM_INLINE_MAX_CHARS = 28
"""Longest rendered enum list inlined into a signature; longer sets stay in the doc."""

PATTERN_INLINE_MAX_CHARS = 20
"""Longest regex inlined into a signature; longer patterns stay in the doc."""


def render_type(info: JsonDict) -> str:
    """Render a JSON Schema property type as a compact signature type."""
    declared = info.get("type")
    if isinstance(declared, str):
        return declared
    if isinstance(declared, list):
        non_null = [str(item) for item in declared if item != "null"]
        return "|".join(non_null) if non_null else "any"
    for key in ("anyOf", "oneOf"):
        branches = info.get(key)
        if not isinstance(branches, list):
            continue
        names: list[str] = []
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            branch_type = branch.get("type")
            if isinstance(branch_type, str) and branch_type != "null" and branch_type not in names:
                names.append(branch_type)
            elif "items" in branch and "array" not in names:
                names.append("array")
        if names:
            return "|".join(names)
    return "string" if "enum" in info else "any"


def render_constraint(info: JsonDict) -> str:
    """Render an enum or regex constraint when it fits inline."""
    enum_values = info.get("enum")
    if isinstance(enum_values, list) and enum_values:
        rendered = "|".join(str(value) for value in enum_values)
        if 0 < len(rendered) <= ENUM_INLINE_MAX_CHARS:
            return f"={rendered}"
    pattern = info.get("pattern")
    if isinstance(pattern, str) and 0 < len(pattern) <= PATTERN_INLINE_MAX_CHARS:
        return f"~{pattern}"
    return ""


def render_signature(func_name: str, input_schema: JsonDict, *, required_only: bool = False) -> str:
    """Render ``name(param:type, optional?:type~constraint)`` for one tool.

    Required parameters come first so a long optional tail cannot bury them; both
    groups keep the schema's (canonicalised) order for a deterministic prompt.

    ``required_only`` is the middle rung of the L2 budget ladder: optionals are
    replaced by ``…`` so the model knows they exist and can read the tool doc for them.

    A schema that declares properties but none of them renderable echoes ``(…)``
    rather than ``()``: an empty signature would read as a zero-argument tool and
    send the model to a call the server then rejects.
    """
    properties = input_schema.get("properties") if isinstance(input_schema, dict) else None
    if not isinstance(properties, dict) or not properties:
        return f"{func_name}()"
    required = input_schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()
    params: list[tuple[bool, str]] = []
    omitted = False
    for name, info in properties.items():
        if not isinstance(info, dict):
            continue
        is_optional = name not in required_names
        if required_only and is_optional:
            omitted = True
            continue
        marker = "?" if is_optional else ""
        params.append((is_optional, f"{name}{marker}:{render_type(info)}{render_constraint(info)}"))
    if omitted:
        params.append((True, "…"))
    if not params:
        return f"{func_name}(…)"
    params.sort(key=lambda item: (item[0], item[1]))
    return f"{func_name}({', '.join(text for _, text in params)})"

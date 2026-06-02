"""JSON Schema documentation utilities for MCP tool documentation.

[INPUT]
- JSON Schema parameter definitions from MCP tool schemas.

[OUTPUT]
- extract_schema_constraints: Formats JSON Schema constraints as markdown documentation lines.
- build_params_section: Builds full parameters documentation section from JSON Schema.
- build_call_example: Generates minimal call example string from required parameters.
- TOOL_DOC_TEMPLATE: Template for single tool documentation (Level 3).

[POS]
Extracts and renders JSON Schema constraint fields (pattern, enum, default, format, min/max, etc.)
into human-readable markdown, enabling Agent LLMs to generate correct MCP tool arguments on first try.
"""

from __future__ import annotations

from typing import Any

type JsonDict = dict[str, Any]

TOOL_DOC_TEMPLATE = """# {tool_name}

## Description

{tool_desc}

{params_section}

## Returns

Returns a **parsed Python object** (dict, list, str, int, etc.), NOT a JSON string.
Do NOT call `json.loads()` on the result. Use it directly like `result['key']` or `for item in result`.

## Import & Call Example

```python
from skills.{skill_name} import {tool_name}

result = {tool_name}({call_example})
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
    """Build parameters documentation section with full JSON Schema constraints."""
    if not input_schema or "properties" not in input_schema:
        return "## Parameters\n\nNo parameters required."

    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])

    lines = ["## Parameters\n"]
    for param_name, param_info in properties.items():
        if not isinstance(param_info, dict):
            continue
        param_type = param_info.get("type", "any")
        param_desc = param_info.get("description", "No description")
        is_required = param_name in required

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


def build_call_example(input_schema: JsonDict) -> str:
    """Build a minimal call example string from required parameters.

    Generates `name="..."` style arguments for each required parameter,
    using example values from JSON Schema when available.
    """
    if not isinstance(input_schema, dict) or "properties" not in input_schema:
        return ""
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))
    parts: list[str] = []
    for name, info in properties.items():
        if name not in required:
            continue
        if not isinstance(info, dict):
            continue
        ptype = info.get("type", "string")
        example = info.get("examples", [None])[0] if info.get("examples") else None
        if example is not None:
            parts.append(f'{name}="{example}"' if ptype == "string" else f"{name}={example}")
        elif ptype == "string":
            parts.append(f'{name}="..."')
        elif ptype in ("integer", "number"):
            parts.append(f"{name}=0")
        elif ptype == "boolean":
            parts.append(f"{name}=True")
        else:
            parts.append(f"{name}=...")
    return ", ".join(parts)

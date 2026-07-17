"""Skill attenuation tool_choice helpers (prefix-cache safe).

[INPUT]
- (none — pure functions over ModelRequest.tools entries)

[OUTPUT]
- extract_bound_tool_names(): names from bound tool objects or OpenAI dict schemas
- build_allowed_tools_tool_choice(): OpenAI ``allowed_tools`` tool_choice payload

[POS]
Skill attenuation request metadata builder. Keeps bind_tools prefix stable while
SkillAttenuationMiddleware restricts per-turn callable tools via tool_choice.
"""

from __future__ import annotations

from typing import Any


def extract_bound_tool_names(tools: list[object]) -> list[str]:
    """Extract tool names from ModelRequest.tools entries."""
    names: list[str] = []
    for tool in tools:
        name = _tool_name(tool)
        if name:
            names.append(name)
    return names


def build_allowed_tools_tool_choice(allowed_names: frozenset[str]) -> dict[str, Any]:
    """Build OpenAI-compatible tool_choice for per-turn tool restriction."""
    return {
        "type": "allowed_tools",
        "mode": "auto",
        "tools": [{"type": "function", "name": name} for name in sorted(allowed_names)],
    }


def _tool_name(tool: object) -> str | None:
    name_attr = getattr(tool, "name", None)
    if isinstance(name_attr, str) and name_attr:
        return name_attr

    if isinstance(tool, dict):
        direct = tool.get("name")
        if isinstance(direct, str) and direct:
            return direct
        function = tool.get("function")
        if isinstance(function, dict):
            fn_name = function.get("name")
            if isinstance(fn_name, str) and fn_name:
                return fn_name

    return None

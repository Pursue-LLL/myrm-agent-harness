"""Domain skill type definitions.

[INPUT]
- (none)

[OUTPUT]
- DomainTool: Declaration of a single executable domain tool.
- DomainSkillManifest: Manifest declaring tools for a specific domain set.

[POS]
Type definitions for the domain executable skills subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DomainTool:
    """Declaration of a single executable domain tool."""

    name: str
    description: str
    script_path: str
    callable_name: str
    args: dict[str, dict[str, str]] = field(default_factory=dict)
    returns_description: str = ""


@dataclass(frozen=True, slots=True)
class DomainSkillManifest:
    """Manifest declaring executable tools for a domain set.

    Each manifest maps a set of domains (glob patterns supported) to
    a collection of Python tools that can be executed via the browser
    session sandbox.
    """

    id: str
    name: str
    domains: tuple[str, ...]
    python_tools: dict[str, DomainTool] = field(default_factory=dict)

    def tool_signatures(self) -> str:
        """Format tool signatures for navigate injection (~20 tokens per tool)."""
        if not self.python_tools:
            return ""
        parts: list[str] = []
        for tool in self.python_tools.values():
            args_str = ", ".join(f"{k}{'?' if a.get('required') != 'true' else ''}" for k, a in tool.args.items())
            parts.append(f"{tool.name}({args_str})")
        return ", ".join(parts)

"""Skill dependency declarations and MCP skill payload types.

[INPUT]
- types_coercion._coerce_str_list (POS: safe list coercion)

[OUTPUT]
- SkillRequires: bins/env/config dependency declaration
- MCPSkillData: MCP server skill payload

[POS]
Dependency and MCP-specific skill data types used by SkillMetadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from myrm_agent_harness.backends.skills.types_coercion import _coerce_str_list


@dataclass
class SkillRequires:
    """Skill dependency declaration.

    Specifies external dependencies that must be satisfied for the skill to be usable.
    Checked at load time; results are cached in SkillMetadata.available.
    """

    bins: list[str] = field(default_factory=list)
    """Required executables that must be on PATH (checked via shutil.which)"""

    env: list[str] = field(default_factory=list)
    """Required environment variables that must be set"""

    config: list[str] = field(default_factory=list)
    """Required config file paths that must exist"""

    def to_dict(self) -> dict[str, list[str]]:
        return {"bins": self.bins, "env": self.env, "config": self.config}

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> SkillRequires:
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            bins=_coerce_str_list(data.get("bins")),
            env=_coerce_str_list(data.get("env")),
            config=_coerce_str_list(data.get("config")),
        )


@dataclass
class MCPSkillData:
    """MCP skill-specific data.

    Contains information for MCP (Model Context Protocol) skills,
    which are dynamically generated from MCP server configurations.
    """

    server: str
    """MCP server name"""

    tools: list[str]
    """Available tool names"""

    config: list[dict[str, object]]
    """MCP server configuration"""

    skill_content: str | None = None
    """Cached SKILL.md content (generated on-demand)"""

    tool_docs: dict[str, str] = field(default_factory=dict)
    """Tool documentation (Level 3: progressive disclosure)"""

    tool_schemas: dict[str, dict[str, object]] = field(default_factory=dict)
    """Tool parameter schemas"""

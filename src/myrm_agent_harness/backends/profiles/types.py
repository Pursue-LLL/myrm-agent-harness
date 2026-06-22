"""Agent Profile type definitions.

[INPUT]
- myrm_agent_harness.toolkits.memory.config::AgentMemoryPolicy (POS: Agent 记忆策略配置)

[OUTPUT]
- AgentProfile: Agent 配置数据结构
- CommandBinding: Slash command to Skill(s) binding (single or multi-skill bundle)
- BuiltInAgent: 内置 Agent 模板数据结构

[POS]
Agent Profile 数据类型定义。AgentProfile 为用户/业务层创建的 Agent 配置，
BuiltInAgent 为框架提供的开箱即用 Agent 模板。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from myrm_agent_harness.toolkits.memory.config import AgentMemoryPolicy


@dataclass(frozen=True, slots=True)
class CommandBinding:
    """Mapping from a user-defined slash command to one or more Skills.

    Stored in AgentProfile.command_bindings so each agent can have its own
    set of shortcut commands. When ``skill_ids`` contains multiple entries,
    the command triggers a *skill bundle* — all SOPs are merged and injected
    into a single LLM turn.
    """

    command_name: str
    """Canonical name without slash (e.g. "daily-report")."""

    skill_ids: tuple[str, ...]
    """Target Skill identifiers to invoke (single or bundle)."""

    description: str = ""
    """User-facing description shown in /help and input hints."""

    aliases: tuple[str, ...] = ()
    """Alternative names for this command."""

    instruction: str = ""
    """Ephemeral guidance injected alongside the SOP(s) for this bundle."""


@dataclass
class AgentProfile:
    """Agent Profile data structure (framework layer).

    Framework-agnostic: no user_id, no deployment mode awareness.
    Business layers extend via the ``metadata`` dict.
    """

    id: str
    """Unique identifier (lowercase alphanumeric, hyphens, underscores)."""

    display_name: str | None = None
    """Human-friendly display name."""

    description: str | None = None
    """Profile description."""

    avatar: str | None = None
    """Avatar reference: home:// | http(s):// | /local/path"""

    model: str | None = None
    """LLM model name (overrides global config)."""

    max_iterations: int | None = None
    """Maximum agent iterations."""

    skills: list[str] | None = None
    """Bound skill IDs."""

    skill_configs: dict[str, dict] | None = None
    """Per-agent skill configurations (e.g. is_core)."""

    tools_allowed: list[str] | None = None
    """Allowed tool names (permission control)."""

    system_prompt: str | None = None
    """System prompt (typically loaded from prompt.md.j2)."""

    memory_policy: AgentMemoryPolicy | None = None
    """Memory read/write boundary policy for this agent."""

    command_bindings: list[CommandBinding] | None = None
    """User-defined slash command → Skill bindings for this agent."""

    metadata: dict[str, object] = field(default_factory=dict)
    """Business-layer extension fields (e.g. home_directory, permissions)."""

    built_in: bool = False
    """Whether this is a built-in profile."""

    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class BuiltInAgent:
    """Built-in Agent template provided by the framework."""

    id: str
    """Template unique identifier."""

    display_name: str
    """Display name."""

    description: str
    """Template description."""

    icon_id: str
    """Icon identifier for the agent avatar (maps to frontend icon registry)."""

    skills: list[str]
    """Preset skill list."""

    system_prompt: str
    """System prompt."""

    model: str | None = None
    """Recommended model."""

    max_iterations: int | None = None
    """Recommended iteration limit."""

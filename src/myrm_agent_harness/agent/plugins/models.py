"""Shared data models for Agent Plugins 1.0.0 parsing.

These dataclasses are the [OUTPUT] of the Agent Plugins parser. The business
layer consumes them to install skills into the SkillStore and persist MCP
servers into the global ``mcpServers`` config. The parser itself never persists.

[INPUT]
-- (none)

[OUTPUT]
-- PluginSkill / PluginMcpServer / PluginDiagnostic / PluginParseResult /
   PluginDiagnosticLevel: parser output contract consumed by the business layer.

[POS]
Shared parser output dataclasses for Agent Plugins 1.0.0 (client-agnostic).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PluginDiagnosticLevel(StrEnum):
    """Severity of a component-level parsing diagnostic."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class PluginDiagnostic:
    """A structured per-component failure report (spec §7.2.2 / §11.3)."""

    component: str  # e.g. "plugin", "skill:summarize", "mcp:deployment-api"
    code: str  # stable machine-readable code, e.g. "unsupported_schema"
    message: str  # user/developer-facing summary (non-technical for UI)
    level: PluginDiagnosticLevel = PluginDiagnosticLevel.ERROR


@dataclass(frozen=True)
class PluginSkill:
    """One skill discovered from ``skills/<name>/SKILL.md`` (non-recursive, §7.1)."""

    name: str  # immediate child directory name that contains SKILL.md
    description: str  # parsed from SKILL.md frontmatter description (may be empty)
    content: str  # SKILL.md pure content (frontmatter stripped)
    files: dict[str, bytes] = field(
        default_factory=dict
    )  # all files under the skill dir (relative paths)
    metadata: dict[str, Any] = field(default_factory=dict)  # skill frontmatter metadata

    @property
    def skill_md_content(self) -> str:
        """Return the raw SKILL.md text (frontmatter + body)."""
        return self.files.get("SKILL.md", b"").decode("utf-8", errors="replace")


@dataclass(frozen=True)
class PluginMcpServer:
    """One MCP server entry parsed from mcp.json (§7.2.1).

    ``name`` is the member name in ``mcpServers``. ``command`` is validated to be a
    single bare token or a ``./``-relative plugin path. ``env`` carries only the
    names of configured environment variables (values are stripped for security);
    ``raw_env_values`` retains literal values that reference ${PLUGIN_ROOT}/${PLUGIN_DATA}
    so the business layer can persist key/placeholder pairs without secrets.
    """

    name: str
    server_type: str  # "stdio" | "streamable_http" | "sse"
    command: str | None
    args: list[str] | None
    url: str | None
    headers: dict[str, str] | None
    cwd: str | None
    env_key_names: list[str] = field(default_factory=list)
    raw_env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentPluginManifestMeta:
    """Validated plugin.json metadata (closed schema, §5.2)."""

    name: str
    version: str | None = None
    description: str | None = None
    author: dict[str, str] | None = None
    homepage: str | None = None
    repository: str | None = None
    license: str | None = None
    keywords: tuple[str, ...] = ()


@dataclass
class PluginParseResult:
    """Aggregated parse outcome for a plugin package.

    ``meta`` is ``None`` when ``plugin.json`` is missing/invalid (fatal, no
    components are loaded). ``skills`` and ``servers`` only contain components
    that parsed successfully. ``diagnostics`` captures skipped/invalid
    components so the GUI can surface a component-level report instead of
    failing the whole import.
    """

    meta: AgentPluginManifestMeta | None = None
    skills: list[PluginSkill] = field(default_factory=list)
    servers: list[PluginMcpServer] = field(default_factory=list)
    diagnostics: list[PluginDiagnostic] = field(default_factory=list)
    schemas: list[str] = field(default_factory=list)  # recognized $schema URIs

    def add_diagnostic(
        self,
        component: str,
        code: str,
        message: str,
        level: PluginDiagnosticLevel = PluginDiagnosticLevel.ERROR,
    ) -> None:
        self.diagnostics.append(PluginDiagnostic(component, code, message, level))

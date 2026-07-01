"""Skill runtime metadata (static declaration + computed fields).

[INPUT]
- core.hooks.types::HookDefinition, HookEvent (POS: hook definition types)
- types_enums, types_requires, types_contract, types_security, types_usage (POS: skill subtypes)

[OUTPUT]
- SkillMetadata: core skill runtime representation

[POS]
Primary skill metadata type combining frontmatter fields with load-time computed state.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from myrm_agent_harness.backends.skills.types_contract import SkillContract
from myrm_agent_harness.backends.skills.types_enums import SkillPermission, SkillTrust
from myrm_agent_harness.backends.skills.types_requires import MCPSkillData, SkillRequires
from myrm_agent_harness.backends.skills.types_security import SecurityScanSummary
from myrm_agent_harness.backends.skills.types_usage import SkillUsageStats
from myrm_agent_harness.core.hooks.types import HookDefinition, HookEvent


@dataclass
class SkillMetadata:
    """Skill runtime metadata (static declaration + runtime-computed fields).

    Combines frontmatter-declared fields with runtime-computed state.
    Full content and resources are loaded on-demand (progressive loading).

    Skills can come from two sources:
    - Storage skills: Loaded from file system or database (storage_skill_id is set)
    - MCP skills: Dynamically generated from MCP servers (mcp is set)
    """

    # --- Core identity ---
    name: str
    """Skill name (standardized to end with _skill)"""

    description: str
    """Brief description of what the skill does"""

    token_cost: int | None = None
    """Precise token cost of the full skill SOP, pre-calculated to avoid runtime overhead"""

    # --- Source identification ---
    storage_skill_id: str | None = None
    """ID in storage system (for file-based or database skills)"""

    storage_path: str | None = None
    """Path in storage system (for file-based skills)"""

    mcp: MCPSkillData | None = None
    """MCP-specific data (for MCP skills)"""

    # --- Hook system ---
    hooks: list[tuple[HookEvent, HookDefinition]] = field(default_factory=list)
    """Hook definitions parsed from SKILL.md frontmatter — (event, definition) pairs"""

    allowed_tools: list[str] | None = None
    """Allowed tool names for access control (parsed from SKILL.md)"""

    required_permissions: list[SkillPermission] = field(default_factory=list)
    """Permissions required by this skill (parsed from SKILL.md frontmatter).

    Declared in SKILL.md as:
      required_permissions:
        - file_write
        - shell_exec

    Users must approve these permissions at install time. The system enforces
    them at runtime (tool calls are blocked if permission not granted).
    """

    allowed_domains: list[str] | None = None
    """Allowed domains for outbound network requests (DLP protection).

    If set, tools like WebFetch and Browser-Use will only be allowed to access
    these domains. If None, outbound requests are not restricted by DLP (but
    are still protected by SSRF shield).
    """

    # --- agentskills.io specification fields ---
    license: str | None = None
    """License name or reference (agentskills.io spec)"""

    compatibility: str | None = None
    """Environment requirements, max 500 chars (agentskills.io spec)"""

    metadata: dict[str, str] = field(default_factory=dict)
    """Arbitrary key-value metadata, e.g. author, version (agentskills.io spec)"""

    # --- Dependencies & tool-based conditional activation (from frontmatter) ---

    requires: SkillRequires | None = None
    """External dependency requirements (bins/env/config)"""

    # --- Tool-based conditional activation ---
    requires_tools: list[str] = field(default_factory=list)
    """Skill is hidden from the model when any listed tool is absent from the agent's tool set."""

    fallback_for_tools: list[str] = field(default_factory=list)
    """Skill is hidden when any listed tool IS present (it's a fallback for that tool)."""

    requires_tool_groups: list[str] = field(default_factory=list)
    """Skill is hidden when any listed tool group is not enabled on the agent.
    Group names are defined in ``core.security.tool_registry.TOOL_GROUP_MAP``."""

    fallback_for_tool_groups: list[str] = field(default_factory=list)
    """Skill is hidden when any listed tool group IS enabled (fallback for that group)."""

    required_credential_files: list[str] = field(default_factory=list)
    """Required credential files for this skill (relative to workspace root).

    Examples: ["google_token.json", ".aws/credentials", ".ssh/github_key"]

    These files are validated at skill load time. Missing files are recorded in
    missing_credentials and the skill may be marked unavailable depending on policy.
    """

    credential_env_mapping: dict[str, str] = field(default_factory=dict)
    """Environment variable mappings for credential files.

    Maps environment variable names to credential file paths (relative to workspace).
    Example: {"GOOGLE_TOKEN_PATH": "google_token.json"}

    The framework automatically sets these environment variables pointing to the
    resolved absolute paths within the workspace.
    """

    always: bool = False
    """If True, always included in skill_select_tool XML (get_metadata_summary), not SystemMessage."""

    model_invocable: bool = True
    """Whether the model can auto-select this skill via skill_select_tool.
    When False, the skill is hidden from the model and can only be triggered by the user."""

    user_invocable: bool = True
    """Whether the user can manually trigger this skill (e.g. via / command or UI).
    When False, the skill is hidden from the frontend and can only be auto-selected by the model."""

    version: str | None = None
    """Skill version string for version management"""

    primary_env: str | None = None
    """Primary environment variable name for apiKey auto-mapping (e.g. "BRAVE_API_KEY").
    When set, the system maps a user-configured apiKey to this env var at execution time."""

    oauth_issuer: str | None = None
    """OAuth issuer key used to scope runtime credential injection for this skill."""

    contract: SkillContract | None = None
    """Structured contract parsed from frontmatter for cache-safe routing and fallback docs."""

    evolution_locked: bool = False
    """If True, this skill is locked from automatic evolution (parsed from frontmatter)."""

    scope_agent_id: str | None = None
    """Agent ID that owns this skill, for multi-agent scoping."""

    config_schema: dict[str, object] | None = None
    """JSON Schema describing typed configuration for SkillInstanceConfig.config_overrides.
    Parsed from SKILL.md frontmatter `config-schema` field. When present, enables
    schema-driven UI rendering and config validation on instance create/update."""

    # --- Runtime-computed fields (populated at load time) ---
    trust: SkillTrust = SkillTrust.TRUSTED
    """Trust level determined by physical source directory"""

    content_hash: str | None = None
    """SHA-256 hash of prompt content (computed at load time for tamper detection)"""

    available: bool = True
    """Whether all dependencies in ``requires`` are satisfied"""

    unavailable_reason: str | None = None
    """Human-readable explanation when ``available`` is False"""

    missing_credentials: list[str] = field(default_factory=list)
    """List of required credential files that are missing (runtime-computed).

    Populated at skill load time by credential validator. Empty list means all
    required credentials are present. Non-empty list indicates which files are
    missing, enabling transparent error reporting to users.
    """

    scanner_clean: bool = True
    """Whether the skill content passed security scanning with no findings.
    Default True for TRUSTED skills (skip scan). Computed at load time for
    INSTALLED skills. Used by attenuator to gate allowed_tools widening."""

    scan_summary: SecurityScanSummary | None = None
    """Security scan summary for API exposure and frontend visualization.
    Populated at load/save time. None if not yet scanned."""

    usage_stats: SkillUsageStats = field(default_factory=SkillUsageStats)
    """Usage statistics for forgetting mechanism (runtime-updated).

    Tracks call count, success rate, last used time. Loaded from {skill_dir}/.stats.json.
    Used by SkillForgettingStrategy to identify low-quality or stale skills.
    """

    @property
    def id(self) -> str:
        """Alias for storage_skill_id or name."""
        return self.storage_skill_id or self.name

    @property
    def is_mcp_skill(self) -> bool:
        """Check if this is an MCP skill."""
        return self.mcp is not None

    @property
    def is_storage_skill(self) -> bool:
        """Check if this is a storage-based skill."""
        return self.storage_skill_id is not None

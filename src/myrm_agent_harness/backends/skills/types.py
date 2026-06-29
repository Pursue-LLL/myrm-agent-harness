"""Skill system data types.


[INPUT]
- agent.hooks.types::HookDefinition (POS: Hook 定义类型)

[OUTPUT]
- SkillLifecycleStatus: 技能生命周期状态枚举（ACTIVE/STALE/ARCHIVED）
- SkillTrust: 技能信任级别枚举（INSTALLED/TRUSTED）
- SkillPermission: 技能权限类型枚举（FILE_READ/WRITE/DELETE, SHELL_EXEC, CODE_INTERPRETER, NETWORK_ACCESS, ENV_VAR_ACCESS）
- SkillRequires: 技能依赖声明（bins/env/config），含 to_dict()/from_dict() 序列化
- MCPSkillData: MCP 技能特有数据
- SkillMetadata: 技能运行时元数据（包含静态声明 + 运行时计算字段）
- SecurityFindingDetail: 单个安全发现（threat_type/severity/description）
- SecurityScanSummary: 安全扫描摘要（score/trust_recommendation/finding_counts/findings）
- SkillInstanceConfig: 实例配置（instance_name/env_overrides/config_overrides/state_file）含 to_dict()/from_dict() 序列化
- SkillStateProtocol: 状态持久化协议（save_state/load_state 方法）
- SkillInstance: 技能运行时实例（metadata/instance_name/config/state），一等公民

[POS]
Skill system core data types. Defines skill runtime representation including trust levels, permissions, usage stats, and MCP skill data.

"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum

from myrm_agent_harness.agent.hooks.types import HookDefinition, HookEvent

# Activation criteria limits (aligned with ironclaw security model)
_MAX_KEYWORDS_PER_SKILL = 20
_MAX_PATTERNS_PER_SKILL = 5
_MAX_TAGS_PER_SKILL = 10
_MIN_KEYWORD_TAG_LENGTH = 3
_MAX_PATTERN_LENGTH = 256
_DEFAULT_MAX_CONTEXT_TOKENS = 2000


class SkillTrust(IntEnum):
    """Trust level for a skill, determining its tool authority ceiling.

    SAFETY: Variant ordering matters. The security model relies on
    ``INSTALLED < TRUSTED`` for min() comparisons in trust attenuation.
    Do NOT reorder variants.
    """

    INSTALLED = 0
    """Registry/external skill — restricted to read-only tools."""

    TRUSTED = 1
    """User-placed skill (local/workspace) — full tool access."""


class SkillLifecycleStatus(StrEnum):
    """Lifecycle state for skill curator management.

    Tracks the gradual degradation of unused or low-quality skills:
    active → stale → archived.  Stale skills remain usable but are
    deprioritised in selection; archived skills are excluded from runtime
    entirely but retain their data for recovery.
    """

    ACTIVE = "active"
    """Normal state — fully operational and discoverable."""

    STALE = "stale"
    """Marked as stale — still usable but deprioritised and shown with a warning.
    Auto-recovers to ACTIVE when the skill is successfully used again."""

    ARCHIVED = "archived"
    """Excluded from runtime — data preserved, recoverable via restore."""


class SkillPermission(StrEnum):
    """Permission types that skills can request.

    Skills declare required permissions in SKILL.md frontmatter.
    The system validates these at install time and enforces them at runtime.
    """

    FILE_READ = "file_read"
    """Read files from the workspace"""

    FILE_WRITE = "file_write"
    """Write/modify files in the workspace"""

    FILE_DELETE = "file_delete"
    """Delete files from the workspace"""

    SHELL_EXEC = "shell_exec"
    """Execute shell commands"""

    CODE_INTERPRETER = "code_interpreter"
    """Execute code in sandboxed interpreters (Python, Node.js, etc.)"""

    NETWORK_ACCESS = "network_access"
    """Make network requests (HTTP/HTTPS)"""

    ENV_VAR_ACCESS = "env_var_access"
    """Read/write environment variables"""


@dataclass
class SkillUsageStats:
    """Skill usage statistics and lifecycle state.

    Tracks skill usage patterns for the curator / forgetting mechanism.
    Stored in {skill_dir}/.stats.json for lightweight persistence.

    The ``lifecycle_status`` and ``pinned`` fields extend pure usage
    tracking into lifecycle management — a natural evolution of the
    forgetting mechanism into a full curator system.
    """

    call_count: int = 0
    """Total number of times the skill was invoked"""

    success_count: int = 0
    """Number of successful invocations (no errors)"""

    failure_count: int = 0
    """Number of failed invocations"""

    last_used_at: datetime | None = None
    """Timestamp of last invocation"""

    total_duration_ms: float = 0.0
    """Cumulative duration in milliseconds"""

    # --- Lifecycle management (curator) ---

    lifecycle_status: str = SkillLifecycleStatus.ACTIVE
    """Current lifecycle state (active / stale / archived).
    Persisted in .stats.json and used by the curator engine."""

    pinned: bool = False
    """When True, the skill is exempt from all automated curator transitions
    (stale / archive) and from automated evolution.  User-initiated only."""

    merged_into: str | None = None
    """When archived via consolidation, the name of the umbrella skill this
    was merged into. None if not merged. Used for provenance tracking."""

    created_at: datetime | None = None
    """Timestamp when this stats record was first created.
    Used by the grace_period check to protect newly-discovered skills."""

    @property
    def success_rate(self) -> float:
        """Success rate as a percentage (0.0-1.0)"""
        if self.call_count == 0:
            return 0.0
        return self.success_count / self.call_count

    @property
    def avg_duration_ms(self) -> float:
        """Average duration per invocation"""
        if self.call_count == 0:
            return 0.0
        return self.total_duration_ms / self.call_count

    @property
    def is_active(self) -> bool:
        return self.lifecycle_status == SkillLifecycleStatus.ACTIVE

    @property
    def is_stale(self) -> bool:
        return self.lifecycle_status == SkillLifecycleStatus.STALE

    @property
    def is_archived(self) -> bool:
        return self.lifecycle_status == SkillLifecycleStatus.ARCHIVED

    def to_dict(self) -> dict[str, object]:
        return {
            "call_count": self.call_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_used_at": (self.last_used_at.isoformat() if self.last_used_at else None),
            "total_duration_ms": self.total_duration_ms,
            "success_rate": self.success_rate,
            "avg_duration_ms": self.avg_duration_ms,
            "lifecycle_status": self.lifecycle_status,
            "pinned": self.pinned,
            "merged_into": self.merged_into,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> SkillUsageStats:
        if not data or not isinstance(data, dict):
            return cls()

        last_used_str = data.get("last_used_at")
        last_used_at = None
        if last_used_str and isinstance(last_used_str, str):
            with contextlib.suppress(ValueError):
                last_used_at = datetime.fromisoformat(last_used_str)

        created_at_str = data.get("created_at")
        created_at = None
        if created_at_str and isinstance(created_at_str, str):
            with contextlib.suppress(ValueError):
                created_at = datetime.fromisoformat(created_at_str)

        raw_status = data.get("lifecycle_status", SkillLifecycleStatus.ACTIVE)
        lifecycle_status = (
            raw_status
            if isinstance(raw_status, str) and raw_status in SkillLifecycleStatus.__members__.values()
            else SkillLifecycleStatus.ACTIVE
        )

        def _safe_int(val: object, default: int = 0) -> int:
            try:
                return int(val) if val is not None else default
            except (ValueError, TypeError):
                return default

        def _safe_float(val: object, default: float = 0.0) -> float:
            try:
                import math

                result = float(val) if val is not None else default
                return default if math.isnan(result) or math.isinf(result) else result
            except (ValueError, TypeError):
                return default

        return cls(
            call_count=_safe_int(data.get("call_count", 0)),
            success_count=_safe_int(data.get("success_count", 0)),
            failure_count=_safe_int(data.get("failure_count", 0)),
            last_used_at=last_used_at,
            total_duration_ms=_safe_float(data.get("total_duration_ms", 0.0)),
            lifecycle_status=lifecycle_status,
            pinned=bool(data.get("pinned", False)),
            merged_into=str(data["merged_into"]) if data.get("merged_into") else None,
            created_at=created_at,
        )


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


@dataclass(frozen=True, slots=True)
class SkillContractTrap:
    """Structured caution that should survive skill content degradation."""

    description: str
    mitigation: str
    severity: str = "medium"
    trigger_condition: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "description": self.description,
            "mitigation": self.mitigation,
            "severity": self.severity,
        }
        if self.trigger_condition:
            payload["trigger_condition"] = self.trigger_condition
        return payload


@dataclass(frozen=True, slots=True)
class SkillContractVerification:
    """Structured verification step for confirming skill success."""

    step_id: str
    description: str
    validation_method: str
    expected_output: str | None = None
    is_required: bool = True

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "step_id": self.step_id,
            "description": self.description,
            "validation_method": self.validation_method,
            "is_required": self.is_required,
        }
        if self.expected_output:
            payload["expected_output"] = self.expected_output
        return payload


@dataclass(frozen=True, slots=True)
class SkillContractJudgment:
    """Structured branch point that the model should reason about explicitly."""

    judgment_id: str
    description: str
    condition: str
    true_branch: str
    false_branch: str
    rationale: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "judgment_id": self.judgment_id,
            "description": self.description,
            "condition": self.condition,
            "true_branch": self.true_branch,
            "false_branch": self.false_branch,
        }
        if self.rationale:
            payload["rationale"] = self.rationale
        return payload


@dataclass(frozen=True, slots=True)
class SkillContract:
    """Cache-safe structured contract extracted from skill frontmatter."""

    steps: tuple[str, ...] = ()
    key_judgments: tuple[SkillContractJudgment, ...] = ()
    potential_traps: tuple[SkillContractTrap, ...] = ()
    verification_steps: tuple[SkillContractVerification, ...] = ()
    dependencies: tuple[str, ...] = ()
    estimated_duration_seconds: float | None = None
    success_criteria: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "steps": list(self.steps),
            "key_judgments": [judgment.to_dict() for judgment in self.key_judgments],
            "potential_traps": [trap.to_dict() for trap in self.potential_traps],
            "verification_steps": [step.to_dict() for step in self.verification_steps],
            "dependencies": list(self.dependencies),
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "success_criteria": self.success_criteria,
        }


@dataclass(frozen=True, slots=True)
class SecurityFindingDetail:
    """A single security finding for API/frontend consumption.

    Simplified version of ScanFinding (no line_number, severity as str).
    """

    threat_type: str
    severity: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {
            "threat_type": self.threat_type,
            "severity": self.severity,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class SecurityScanSummary:
    """Security scan summary for API exposure and frontend visualization.

    Score is consistent with trust_recommendation: the recommendation
    determines the score band, and deductions refine within that band.
    """

    score: int
    """0-100 security score. Higher is safer."""

    trust_recommendation: str
    """One of: trusted, installed, untrusted, reject."""

    finding_counts: dict[str, int] = field(default_factory=dict)
    """Finding counts by severity: {critical: N, high: N, medium: N, low: N}."""

    total_findings: int = 0
    """Total number of security findings."""

    findings: tuple[SecurityFindingDetail, ...] = ()
    """Individual findings with threat_type, severity, and description."""

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "trust_recommendation": self.trust_recommendation,
            "finding_counts": self.finding_counts,
            "total_findings": self.total_findings,
            "findings": [f.to_dict() for f in self.findings],
        }


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

    # --- Activation & selection (from frontmatter) ---
    """Activation criteria for deterministic skill selection"""

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


@dataclass
class SkillInstanceConfig:
    """Skill instance configuration for multi-instance support.

    Stored in .myrm/skills/instances/{skill_name}/{instance_name}.json
    Enables multiple instances of the same skill with different configurations.

    Example use cases:
    - github (personal/work): Different API tokens
    - mysql (prod/dev): Different connection strings
    - monitoring (server-1/server-2): Different hosts
    """

    instance_name: str
    """Instance name (e.g., 'personal', 'work', 'prod', 'dev')"""

    skill_name: str
    """Skill name this instance belongs to"""

    created_at: datetime
    """Timestamp when instance was created"""

    updated_at: datetime
    """Timestamp when instance was last updated"""

    env_overrides: dict[str, str] = field(default_factory=dict)
    """Environment variable overrides for this instance.

    Example: {"GITHUB_TOKEN": "ghp_personal_xxx", "GITHUB_ORG": "my-org"}
    These override the default env vars when this instance is loaded.
    """

    config_overrides: dict[str, object] = field(default_factory=dict)
    """Configuration overrides for this instance.

    Example: {"api_base_url": "https://api.custom.com", "timeout": 30}
    Skill-specific configurations that differ per instance.
    """

    state_file: str | None = None
    """Relative path to state file for this instance.

    Example: ".myrm/skills/states/{skill_name}/{instance_name}.json"
    Auto-generated when state persistence is enabled.
    """

    def __post_init__(self) -> None:
        """Validate instance configuration after initialization.

        Validates:
        - instance_name: Non-empty, no whitespace, alphanumeric + underscore/dash only
        - skill_name: Non-empty
        - env_overrides: Keys are non-empty strings, values are non-empty strings
        - config_overrides: Values are JSON-serializable
        """
        import re

        # Validate instance_name
        if not self.instance_name or not isinstance(self.instance_name, str):
            raise ValueError("instance_name must be a non-empty string")
        if self.instance_name != self.instance_name.strip():
            raise ValueError("instance_name cannot contain leading/trailing whitespace")
        if not re.match(r"^[a-zA-Z0-9_-]+$", self.instance_name):
            raise ValueError("instance_name must contain only alphanumeric characters, underscores, and dashes")

        # Validate skill_name
        if not self.skill_name or not isinstance(self.skill_name, str):
            raise ValueError("skill_name must be a non-empty string")

        # Validate env_overrides
        if not isinstance(self.env_overrides, dict):
            raise ValueError("env_overrides must be a dict")
        for key, value in self.env_overrides.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"env_overrides key must be non-empty string, got: {key!r}")
            if not isinstance(value, str):
                raise ValueError(f"env_overrides value must be string, got {type(value).__name__} for key {key!r}")

        # Validate config_overrides
        if not isinstance(self.config_overrides, dict):
            raise ValueError("config_overrides must be a dict")

    def to_dict(self) -> dict[str, object]:
        """Serialize instance config to dict for JSON storage."""
        return {
            "instance_name": self.instance_name,
            "skill_name": self.skill_name,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "env_overrides": self.env_overrides,
            "config_overrides": self.config_overrides,
            "state_file": self.state_file,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SkillInstanceConfig:
        """Deserialize instance config from dict with validation."""
        return cls(
            instance_name=str(data["instance_name"]),
            skill_name=str(data["skill_name"]),
            created_at=datetime.fromisoformat(str(data["created_at"])),
            updated_at=datetime.fromisoformat(str(data["updated_at"])),
            env_overrides=dict(data.get("env_overrides", {})),  # type: ignore
            config_overrides=dict(data.get("config_overrides", {})),  # type: ignore
            state_file=str(data["state_file"]) if data.get("state_file") else None,
        )


class SkillStateProtocol:
    """Protocol for skills that support state persistence.

    Skills implement this protocol to enable automatic state save/load.
    Framework handles serialization to .myrm/skills/states/{skill}/{instance}.json

    Example implementation:
        class GitHubSkill(SkillStateProtocol):
            def save_state(self) -> dict[str, object]:
                return {
                    "last_repo": self.current_repo,
                    "cached_prs": self.pr_cache,
                }

            def load_state(self, state: dict[str, object]) -> None:
                self.current_repo = state.get("last_repo")
                self.pr_cache = state.get("cached_prs", {})
    """

    def save_state(self) -> dict[str, object]:
        """Save skill state to dict.

        Framework serializes this to JSON and stores in:
        .myrm/skills/states/{skill_name}/{instance_name}.json

        Returns:
            dict: State data to persist (JSON-serializable)
        """
        raise NotImplementedError

    def load_state(self, state: dict[str, object]) -> None:
        """Load skill state from dict.

        Called by framework after deserializing JSON state file.
        Skill should restore its internal state from the provided dict.

        Args:
            state: State data loaded from .myrm/skills/states/
        """
        raise NotImplementedError


@dataclass
class SkillInstance:
    """Skill runtime instance (first-class object).

    Represents a concrete skill instance combining:
    - Base metadata (static, from SkillBackend)
    - Instance configuration (overrides)
    - Runtime state (persisted)

    This is the primary object Agent layer interacts with. Backend loads pure
    SkillMetadata; StateManager composes SkillInstance by combining metadata,
    config, and state.

    Design principles:
    1. Pure value object (immutable semantics)
    2. Single source of truth for instance execution
    3. Backend agnostic (works with any SkillBackend)

    Example:
        # Load via StateManager (unified interface)
        instance = state_manager.load_instance("github_skill", "personal")

        # Access merged environment
        token = instance.get_env("GITHUB_TOKEN")  # Instance override priority

        # Access base metadata
        print(instance.metadata.description)

        # Access instance config
        print(instance.config.created_at)
    """

    metadata: SkillMetadata
    """Base skill metadata (static, from SkillBackend)"""

    instance_name: str
    """Instance name (e.g., 'personal', 'work', 'prod', 'dev')"""

    config: SkillInstanceConfig
    """Instance-specific configuration (env/config overrides)"""

    state: dict[str, object]
    """Runtime state (persisted across sessions, JSON-serializable)"""

    def get_env(self, key: str, default: str | None = None) -> str | None:
        """Get environment variable with instance override priority.

        Fallback order:
        1. Instance env_overrides (highest priority)
        2. System environment variables (os.environ)
        3. Default parameter (fallback)

        Args:
            key: Environment variable name
            default: Default value if key not in overrides or system env

        Returns:
            Value from instance overrides, system env, or default
        """
        import os

        # 1. Check instance overrides first
        if key in self.config.env_overrides:
            return self.config.env_overrides[key]

        # 2. Fallback to system environment
        return os.environ.get(key, default)

    def get_config(self, key: str, default: object = None) -> object:
        """Get configuration value with instance override priority.

        Returns value from instance config_overrides, or default if not found.

        Args:
            key: Configuration key
            default: Default value if key not in instance overrides

        Returns:
            Value from instance overrides or default
        """
        return self.config.config_overrides.get(key, default)


def _coerce_str_list(val: object) -> list[str]:
    """Coerce a value to a list of strings (safe for untrusted input)."""
    return [str(v) for v in val] if isinstance(val, list) else []


def skill_visible_for_tools(
    skill: SkillMetadata,
    available_tool_names: frozenset[str],
    available_tool_groups: frozenset[str],
) -> bool:
    """Determine whether *skill* should be visible given the agent's tool set.

    Pure function, no side effects, trivially testable.

    Rules:
    - ``requires_tools``: ALL listed tools must be present → hide if any absent.
    - ``requires_tool_groups``: ALL listed groups must be enabled → hide if any absent.
    - ``fallback_for_tools``: hide when ANY listed tool IS present (primary available).
    - ``fallback_for_tool_groups``: hide when ANY listed group IS enabled.

    Empty lists (default) impose no constraints → skill is always visible.
    """
    for t in skill.requires_tools:
        if t not in available_tool_names:
            return False
    for g in skill.requires_tool_groups:
        if g not in available_tool_groups:
            return False
    for t in skill.fallback_for_tools:
        if t in available_tool_names:
            return False
    return all(g not in available_tool_groups for g in skill.fallback_for_tool_groups)

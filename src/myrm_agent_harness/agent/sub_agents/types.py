"""Subagent system types and enums.

Self-update note: when this file changes, update its INPUT/OUTPUT/POS comments.

[INPUT]
- utils.token_tracker::TokenUsage (POS: Token usage tracking type for prompt/completion/total tokens)
- .hitl_tool_policy::HITL_TOOL_POLICY (POS: HITL tool registry SSOT for subagent blocking)

[OUTPUT]
- CouncilOpinion: Single expert opinion from one council round.
- CouncilResult: Structured result from a council orchestration session.
- SubAgentStatus: Subagent lifecycle status enum.
- SubagentBudgetExceededError: Subagent budget overrun exception.
- CancellationStrategy: Cancellation strategy enum.
- MemoryIsolationPolicy: Memory isolation policy enum.
- DelegateRole: Runtime delegation role enum.
- ControlScope: Trusted control-scope enum.
- DelegationCapabilityManifest: Single source of subagent delegation tool capability policy.
- WorkspacePolicy: Workspace policy enum.
- SubAgentResult: Structured subagent execution result.
- AgentHandoverState: Structured subagent handover state.
- ProgressCalculator: Custom progress calculator protocol.
- ModelResolver: Model name resolver protocol.
- AgentFactory: Agent construction factory protocol.
- SubagentConfig: Declarative subagent configuration.
- SubagentCatalog: Subagent config resolution protocol.
- DELEGATION_CAPABILITY_MANIFEST: Default delegation capability policy.
- _SUBAGENT_DEFAULT_BLACKLIST: Leaf blocked tool set derived from the default capability manifest.

[POS]
Subagent subsystem core type definitions. Defines all subagent-related data types, enums, and protocols.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol

from myrm_agent_harness.agent.sub_agents.hitl_tool_policy import (
    HITL_TOOL_POLICY,
)
from myrm_agent_harness.utils.token_economics.tracker import TokenUsage

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Subagent Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DelegationCapabilityManifest:
    """Subagent delegation capability policy shared by filtering and injection."""

    leaf_blocked_tools: frozenset[str]
    orchestrator_child_tools: tuple[str, ...]
    privileged_skill_tools: frozenset[str]

    @classmethod
    def default(cls) -> DelegationCapabilityManifest:
        orchestrator_child_tools = (
            "delegate_task_tool",
            "subagent_control_tool",
            "send_teammate_message_tool",
        )
        privileged_skill_tools = frozenset(
            {
                "skill_manage_tool",
                "skill_discovery_tool",
            }
        )
        legacy_delegation_tools = frozenset(
            {
                "spawn_subagent_tool",
                "batch_delegate_tasks_tool",
                "list_subagents_tool",
                "cancel_subagent_tool",
                "steer_subagent_tool",
            }
        )
        hitl_tools = HITL_TOOL_POLICY.subagent_blocked
        return cls(
            leaf_blocked_tools=frozenset(orchestrator_child_tools)
            | privileged_skill_tools
            | legacy_delegation_tools
            | hitl_tools,
            orchestrator_child_tools=orchestrator_child_tools,
            privileged_skill_tools=privileged_skill_tools,
        )


DELEGATION_CAPABILITY_MANIFEST = DelegationCapabilityManifest.default()
_SUBAGENT_DEFAULT_BLACKLIST: frozenset[str] = DELEGATION_CAPABILITY_MANIFEST.leaf_blocked_tools


class SubAgentStatus(StrEnum):
    """Subagent lifecycle status."""

    PENDING = "pending"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    CANCELLED_BY_BUDGET = "cancelled_by_budget"
    PENDING_APPROVAL = "pending_approval"
    YIELDED = "yielded"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class CouncilOpinion:
    """A single expert's opinion from one round of a council session."""

    expert_id: str
    agent_type: str
    round_num: int
    content: str
    success: bool
    duration_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class CouncilResult:
    """Structured result from a council orchestration session.

    Captures consensus points, divergences, and the chair's synthesis
    across multiple rounds of independent analysis and cross-review.
    """

    success: bool
    synthesis: str
    consensus_points: tuple[str, ...] = ()
    divergences: tuple[str, ...] = ()
    action_items: tuple[str, ...] = ()
    opinions: tuple[CouncilOpinion, ...] = ()
    rounds_completed: int = 0
    total_duration_seconds: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "synthesis": self.synthesis,
            "consensus_points": list(self.consensus_points),
            "divergences": list(self.divergences),
            "action_items": list(self.action_items),
            "rounds_completed": self.rounds_completed,
            "total_duration_seconds": round(self.total_duration_seconds, 3),
            "opinions": [
                {
                    "expert_id": o.expert_id,
                    "agent_type": o.agent_type,
                    "round_num": o.round_num,
                    "content": o.content[:500],
                    "success": o.success,
                }
                for o in self.opinions
            ],
            **({"error": self.error} if self.error else {}),
        }


class SubagentBudgetExceededError(Exception):
    """Raised when a subagent exceeds its configured budget (tokens or USD)."""

    pass


class CancellationStrategy(StrEnum):
    """Subagent cancellation strategy.

    IMMEDIATE: Force immediate cancellation (default asyncio behavior)
    GRACEFUL: Wait for current tool call to complete before cancelling
    CHECKPOINT: Save intermediate state before cancelling (for resumable tasks)
    """

    IMMEDIATE = "immediate"
    GRACEFUL = "graceful"
    CHECKPOINT = "checkpoint"


class MemoryIsolationPolicy(StrEnum):
    """Subagent memory isolation policy."""

    EPHEMERAL_SESSION = "ephemeral_session"
    READ_ONLY_GLOBAL = "read_only_global"
    COLLABORATIVE_SESSION = "collaborative_session"


class DelegateRole(StrEnum):
    """Runtime delegation role requested by the delegating agent."""

    LEAF = "leaf"
    ORCHESTRATOR = "orchestrator"


class ControlScope(StrEnum):
    """Maximum control scope allowed by trusted configuration."""

    ORCHESTRATOR = "orchestrator"
    LEAF = "leaf"


class WorkspacePolicy(StrEnum):
    """Subagent workspace isolation policy."""

    INHERIT = "inherit"
    ISOLATED_COPY = "isolated_copy"
    READ_ONLY_SANDBOX = "read_only_sandbox"


@dataclass
class SubAgentResult:
    """Structured subagent execution result."""

    success: bool
    task_id: str
    agent_type: str
    result: str = ""
    error: str = ""
    token_usage: TokenUsage | None = None
    duration_seconds: float = 0.0
    completed_at: float = 0.0
    status: SubAgentStatus = SubAgentStatus.COMPLETED
    trace_id: str = ""
    checkpoint_data: dict[str, object] | None = None
    """Checkpoint data (messages, variables, progress) if resumed from checkpoint"""
    payload: dict[str, object] | None = None
    """Interrupt payload if status is PENDING_APPROVAL"""
    handover_state: AgentHandoverState | None = None
    """Structured handover state generated by the agent upon completion."""
    accumulated_duration_seconds: float | None = None
    """Total runtime across interruptions (previous + current duration)."""
    still_running: bool = False
    """True when a wait timeout fired but the agent continues in background."""

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "success": self.success,
            "task_id": self.task_id,
            "agent_type": self.agent_type,
            "result": self.result,
            "status": self.status.value,
            "duration_seconds": round(self.duration_seconds, 3),
        }
        if not self.still_running:
            data["completed_at"] = self.completed_at
        if self.trace_id:
            data["trace_id"] = self.trace_id
        if self.error:
            data["error"] = self.error
        if self.token_usage:
            data["token_usage"] = self.token_usage.to_dict()
        if self.payload:
            data["payload"] = self.payload
        if self.checkpoint_data:
            data["checkpoint_data"] = self.checkpoint_data
        if self.handover_state:
            data["handover_state"] = self.handover_state.to_dict()
        if self.accumulated_duration_seconds is not None:
            data["accumulated_duration_seconds"] = round(self.accumulated_duration_seconds, 3)
        if self.still_running:
            data["still_running"] = True
        return data


@dataclass(frozen=True, slots=True)
class AgentHandoverState:
    """Structured handover state from a completed subagent to its caller/successors.

    Prevents token explosion by passing this concise state instead of raw transcripts.
    """

    task_completed: list[str] = field(default_factory=list)
    pending_todos: list[str] = field(default_factory=list)
    risks_or_notes: list[str] = field(default_factory=list)
    relevant_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "task_completed": self.task_completed,
            "pending_todos": self.pending_todos,
            "risks_or_notes": self.risks_or_notes,
            "relevant_files": self.relevant_files,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AgentHandoverState:
        def string_list(key: str) -> list[str]:
            value = data.get(key)
            if not isinstance(value, list):
                return []
            return [item for item in value if isinstance(item, str)]

        return cls(
            task_completed=string_list("task_completed"),
            pending_todos=string_list("pending_todos"),
            risks_or_notes=string_list("risks_or_notes"),
            relevant_files=string_list("relevant_files"),
        )


class ProgressCalculator(Protocol):
    """Protocol for custom progress calculation in subagents.

    Allows business layer to inject custom progress calculation logic.
    """

    def calculate_progress(
        self,
        current_tokens: int,
        budget_tokens: int | None,
        tool_count: int,
        elapsed_seconds: float,
    ) -> dict[str, object]:
        """Calculate custom progress data.

        Args:
            current_tokens: Cumulative tokens consumed
            budget_tokens: Token budget (None if unlimited)
            tool_count: Number of tools completed
            elapsed_seconds: Elapsed time since start

        Returns:
            Dict with at least 'progress' key (0.0-1.0), plus any custom fields
        """
        ...


class ModelResolver(Protocol):
    """Protocol for resolving a model name string to a BaseChatModel instance.

    Enables the business layer to inject model resolution logic into the
    framework's bare BaseAgent path (YAML presets / dynamic subagents).
    Without this, config.model is logged but silently falls back to parent LLM.

    Usage:
        Set SubagentConfig.model_resolver or inject via SubagentManager.
    """

    async def resolve(
        self,
        model_name: str,
        complexity_tier: str | None = None,
        task_description: str | None = None,
    ) -> object:
        """Resolve a model name to a BaseChatModel instance.

        Args:
            model_name: The model identifier (e.g., 'gpt-4o-mini').
            complexity_tier: Optional explicit complexity tier ('simple', 'standard', 'reasoning').
            task_description: Optional task description to aid in auto-routing.

        Returns:
            A BaseChatModel instance ready for use.

        Raises:
            ValueError: If the model cannot be resolved.
        """
        ...


class AgentFactory(Protocol):
    """Protocol for building fully-configured child agents.

    When SubagentConfig.agent_factory is set, build_child_agent() delegates
    construction to this factory instead of creating a bare BaseAgent.

    This enables the business layer to inject rich agent construction logic
    (e.g., SkillAgent with memory, skills, MCP) without
    leaking business concepts into the framework layer.

    The framework layer only knows: "I get back a BaseAgent" — it does not
    care whether it is a SkillAgent, a custom subclass, or a plain BaseAgent.
    """

    async def build(
        self,
        config: SubagentConfig,
        tools: list[object],
        task_description: str,
        parent_agent: object,
        current_depth: int,
        complexity_tier: str | None = None,
    ) -> object:
        """Build a fully-configured agent instance.

        Args:
            config: The SubagentConfig that triggered this build.
            tools: Pre-filtered tools (L1-L3 already applied).
            task_description: The task delegated to the child agent.
            parent_agent: The parent BaseAgent instance.
            current_depth: Current spawn depth.
            complexity_tier: Optional model routing tier.

        Returns:
            A BaseAgent (or subclass) instance, ready to run().
        """
        ...


@dataclass(frozen=True, slots=True)
class SubagentConfig:
    """Declarative subagent configuration.

    Tool safety: 4-layer isolation
      Layer 0 (type admission): allowed_types on create_delegate_task_tool restricts spawnable agent types
      Layer 1 (global blacklist): _SUBAGENT_DEFAULT_BLACKLIST — orchestrator delegation tools + legacy aliases + skill management
      Layer 2 (per-config): tools (allowlist) + disallowed_tools (blocklist) from this config
      Layer 3 (parent constraint): child ⊆ parent intersection (enforced by SubagentManager._filter_tools)

    Model resolution (3-level chain):
      1. llm (pre-built instance, highest priority)
      2. model (string name, resolved via LLMManager by business layer)
      3. parent LLM (inherited from parent agent, default)

    Agent construction:
      When agent_factory is set, build_child_agent() delegates full agent construction
      to the factory (e.g., creating a SkillAgent with memory, skills, MCP).
      When agent_factory is None, build_child_agent() creates a bare BaseAgent (default).
    """

    system_prompt: str
    tools: tuple[str, ...] = field(default_factory=tuple)
    disallowed_tools: frozenset[str] = field(default_factory=frozenset)
    description: str = ""
    display_name: str = ""
    theme_color: str = ""
    model: str | None = None
    llm: object | None = field(default=None, repr=False)
    timeout_seconds: int = 120
    concurrency_limit: int = 5
    max_turns: int = 25
    max_retries: int = 3
    retry_backoff_seconds: float = 2.0
    max_spawn_depth: int = 0
    budget_tokens: int | None = None
    max_cost_usd: float | None = None
    max_result_tokens: int | None = None
    max_children_per_agent: int = 5
    max_descendants_per_run: int = 20
    max_batch_size: int = 5
    auto_vault_threshold: int | None = 8000
    """Auto-vault threshold in characters. When subagent output exceeds this,
    the result is stored in ArtifactVault and a summary + vault:// pointer
    is returned instead of truncating. Set to None to disable. Default 8000 chars ≈ 2000 tokens."""
    max_error_chars: int = 2000
    """Maximum characters for error messages returned to the parent agent.
    Longer errors are compacted to head + truncation marker + tail to prevent
    context pollution. Set to 0 to disable compaction."""
    progress_calculator: ProgressCalculator | None = None
    cancellation_strategy: CancellationStrategy = CancellationStrategy.GRACEFUL
    graceful_cancel_timeout_seconds: float = 5.0
    memory_isolation: MemoryIsolationPolicy = MemoryIsolationPolicy.EPHEMERAL_SESSION
    control_scope: ControlScope = ControlScope.LEAF
    delegation_role: DelegateRole = DelegateRole.LEAF
    workspace_policy: WorkspacePolicy = WorkspacePolicy.INHERIT
    context_mode: Literal["isolated", "fork"] = "isolated"
    max_fork_tokens: int | None = None
    model_resolver: ModelResolver | None = field(default=None, repr=False)
    agent_factory: AgentFactory | None = field(default=None, repr=False)
    stale_after_seconds: int = 300
    """Seconds without token/tool progress before emitting SUBAGENT_STALE.
    Only checked when TOKEN_USAGE events arrive; fully-hung agents (zero events)
    are caught by the hard timeout instead."""
    in_tool_stale_multiplier: int = 4
    """Multiplier applied to stale_after_seconds while a tool call is active,
    to avoid false positives on legitimately slow tools (e.g. web scraping)."""
    stale_auto_cancel: bool = False
    """If True, automatically cancel the subagent when staleness is detected.
    Defaults to False (warn only) to avoid killing tasks that are slow but alive."""
    delegation_catalog: SubagentCatalog | None = field(default=None, repr=False)
    delegation_allowed_types: frozenset[str] | None = field(default=None, repr=False)


class SubagentCatalog(Protocol):
    """Protocol for resolving subagent configurations.

    Replaces the global SUBAGENT_CONFIGS dictionary, allowing the business layer
    to resolve subagents from databases (e.g., custom saved agents) or YAML presets.
    """

    async def resolve(self, type_id: str) -> SubagentConfig | None:
        """Resolve a subagent configuration by its type ID or agent ID.

        Args:
            type_id: The identifier for the subagent (e.g., 'coder' or a UUID).

        Returns:
            The resolved SubagentConfig, or None if not found.
        """
        ...

    async def list_available(self) -> list[str]:
        """List all available subagent type IDs."""
        ...


SUBAGENT_CONFIGS: dict[str, SubagentConfig] = {}
"""[DEPRECATED] Registry of subagent configurations.
Use SubagentCatalog protocol instead."""

# NOTE: Global registry and registration functions have been moved to registry.py
# for better separation of concerns. Import from there:
# from .registry import SUBAGENT_CONFIGS, register_subagent_configs, etc.

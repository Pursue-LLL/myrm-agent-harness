"""Hook system type definitions — framework-agnostic.

Defines lifecycle events, hook definitions, payloads, and results.
Usable by both agent/ and toolkits/ without coupling to the agent runtime.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Lifecycle Events
# ---------------------------------------------------------------------------


class HookEvent(StrEnum):
    """Built-in lifecycle events that trigger hooks.

    HookRegistry also accepts arbitrary string keys for custom events.
    """

    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    POST_TOOL_USE_FAILURE = "post_tool_use_failure"
    POST_TOOL_USE_CANCELLED = "post_tool_use_cancelled"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_STOP = "subagent_stop"
    SUBAGENT_CANCEL_REQUEST = "subagent_cancel_request"
    SUBAGENT_CANCEL_START = "subagent_cancel_start"
    SUBAGENT_CANCEL_COMPLETE = "subagent_cancel_complete"
    PRE_COMPACT = "pre_compact"
    MEMORY_ARCHIVED = "memory_archived"
    USER_TURN = "user_turn"
    TRACE_SLICE_READY = "trace_slice_ready"
    SKILL_LEARNED = "skill_learned"
    APPROVAL_CORRECTION = "approval_correction"


# ---------------------------------------------------------------------------
# Hook Definitions (4 types)
# ---------------------------------------------------------------------------


class _HookBase(BaseModel):
    """Shared fields for all hook types."""

    matcher: str | None = Field(default=None, description="fnmatch pattern to filter tool names (e.g. 'bash_*')")
    block_on_failure: bool = Field(default=False, description="If true, a failed hook blocks the main flow")
    timeout_seconds: int = Field(default=30, ge=1, le=600)


HookCallable = Callable[[str, dict[str, object]], Awaitable["HookResult"]]


class CallableHookDefinition(_HookBase):
    """Python async callable registered programmatically."""

    type: Literal["callable"] = "callable"
    fn: HookCallable

    model_config = {"arbitrary_types_allowed": True}


class CommandHookDefinition(_HookBase):
    """Shell command hook. Supports $ARGUMENTS template injection."""

    type: Literal["command"] = "command"
    command: str


class HttpHookDefinition(_HookBase):
    """Webhook POST hook for SaaS audit integration."""

    type: Literal["http"] = "http"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class LLMHookDefinition(_HookBase):
    """LLM-based intelligent validation hook."""

    type: Literal["llm"] = "llm"
    prompt: str = Field(description="Prompt template, supports $ARGUMENTS")
    model: str | None = Field(default=None, description="Model name, None = default")
    depth: Literal["quick", "thorough"] = Field(
        default="quick", description="quick ≈ fast validation, thorough ≈ deep reasoning"
    )


HookDefinition = CallableHookDefinition | CommandHookDefinition | HttpHookDefinition | LLMHookDefinition


# ---------------------------------------------------------------------------
# Hook Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HookResult:
    """Result from a single hook execution."""

    hook_type: str
    success: bool
    output: str = ""
    blocked: bool = False
    reason: str = ""
    updated_input: dict[str, object] | None = None
    additional_context: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    elapsed_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class AggregatedHookResult:
    """Aggregated result from multiple hooks for a single event."""

    results: tuple[HookResult, ...] = ()

    @property
    def blocked(self) -> bool:
        return any(r.blocked for r in self.results)

    @property
    def reason(self) -> str:
        for r in self.results:
            if r.blocked:
                return r.reason or r.output
        return ""

    @property
    def updated_input(self) -> dict[str, object] | None:
        """Last hook providing updated_input wins (cascade override)."""
        for r in reversed(self.results):
            if r.updated_input is not None:
                return r.updated_input
        return None

    @property
    def additional_contexts(self) -> list[str]:
        return [r.additional_context for r in self.results if r.additional_context]

    @property
    def all_succeeded(self) -> bool:
        return all(r.success for r in self.results)


# ---------------------------------------------------------------------------
# Event Payloads
# ---------------------------------------------------------------------------

EMPTY_RESULT = AggregatedHookResult()


@dataclass(frozen=True, slots=True)
class PreToolUsePayload:
    tool_name: str
    tool_input: dict[str, object]
    tool_call_id: str
    session_id: str = ""
    agent_id: str | None = None
    agent_type: str | None = None


@dataclass(frozen=True, slots=True)
class PostToolUsePayload:
    tool_name: str
    tool_input: dict[str, object]
    tool_output: str
    tool_call_id: str
    session_id: str = ""
    agent_id: str | None = None
    agent_type: str | None = None


@dataclass(frozen=True, slots=True)
class PostToolUseFailurePayload:
    tool_name: str
    tool_input: dict[str, object]
    error: str
    tool_call_id: str
    session_id: str = ""
    agent_id: str | None = None
    agent_type: str | None = None


@dataclass(frozen=True, slots=True)
class SessionStartPayload:
    session_id: str
    workspace_path: str = ""


@dataclass(frozen=True, slots=True)
class SessionEndPayload:
    session_id: str
    total_tokens: int = 0
    total_cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class MemoryArchivedPayload:
    session_id: str
    agent_id: str
    archived_count: int
    duration_ms: float


@dataclass(frozen=True, slots=True)
class SubagentStartPayload:
    task_id: str
    agent_type: str
    task_description: str


@dataclass(frozen=True, slots=True)
class SubagentStopPayload:
    task_id: str
    agent_type: str
    success: bool
    result: str = ""
    error: str = ""
    duration_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class SubagentMergeConflictPayload:
    task_id: str
    agent_type: str
    branch: str
    conflicting_files: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True, slots=True)
class PreCompactPayload:
    session_id: str
    message_count: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class TraceSliceReadyPayload:
    session_id: str
    tool_call_ids: list[str]
    agent_id: str | None = None
    agent_type: str | None = None


@dataclass(frozen=True, slots=True)
class SkillLearnedPayload:
    session_id: str
    skill_name: str
    skill_description: str
    agent_id: str | None = None
    is_global: bool = False


@dataclass(frozen=True, slots=True)
class ApprovalCorrectionPayload:
    """Payload emitted when user edits/rejects tool calls in the approval flow.

    Each correction carries the tool name, decision type, original args,
    and revised args (for edits) so downstream hooks can learn from the signal.
    """

    session_id: str
    corrections: tuple[dict[str, object], ...]
    agent_id: str | None = None


@dataclass(frozen=True, slots=True)
class UserTurnPayload:
    session_id: str
    user_input: str
    agent_id: str | None = None


@runtime_checkable
class HookRegistryProtocol(Protocol):
    """Minimal hook registry interface for cross-layer dependency injection."""

    _hooks: dict[str, list[HookDefinition]]

    def register(self, event: str | HookEvent, hook: HookDefinition) -> None: ...

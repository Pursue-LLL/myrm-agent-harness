"""Context management shared data structures.

 Self-update reminder: once this file is updated, also update:
1. The INPUT/OUTPUT/POS comments in this file
3. agent/context_management/PROMPT_CACHE_PRACTICE.md §4.2 compress_min_save

[INPUT]
- langchain_core.messages::BaseMessage (POS: LangChain message base class)

[OUTPUT]
- CacheUsageFeedback: Strongly typed provider cache usage feedback for pruning decisions
- CompactToolCall: Compact tool call dataclass (compressed tool call format)
- CompressionIntent: Structured compression focus (injected by server / plane)
- StructuredSummary: Structured summary dataclass (deterministic output, not free-form)
- ContextConfig: Context configuration (compress_threshold, summarize_threshold, keep_recent_calls)
- ToolProtectionConfig: Tool protection configuration (defines non-compressible tools)
- EvictedToolCall: Evicted tool call dataclass (contains original uncompressed content)
- SummaryPersistCallback: Summary persistence callback protocol (dependency inversion)
- ContextCompressOffloadCallback: Tool result offload callback for compression/pruning (optional)
- ContextOffloadResult: Strongly typed offload result with failure taxonomy
- ContextSnapshotCallback: Pre-compression full message snapshot callback (optional)
- BUILTIN_PROTECTED_TOOLS: Built-in protected tools list
- DEFAULT_BUSINESS_PROTECTED_TOOLS: Default business protected tools list
- DEFAULT_CONTEXT_CONFIG: Default context configuration (128k window)
- TOOL_PROTECTION_CONFIG: Default tool protection configuration
- COMPRESS_MIN_SAVE_DEFAULT: Minimum compression savings threshold
- get_compress_min_save_for_model(): Get compress_min_save value

[POS]
Context management shared data structures. Defines compact format types, summary schemas, and configuration constants as the type-system foundation for context management.

"""

from __future__ import annotations

import json
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

# Minimum compression savings threshold (Prompt Cache protection).
# See CONTEXT_ENGINEERING.md §5.2.
# Assumes T_prefix=30k, T_cleared > T_prefix * (1-P), at 90% discount: 30k * 0.1 = 3k.
# 3000 tokens balances cache protection without being overly conservative.
COMPRESS_MIN_SAVE_DEFAULT: int = 3000


def get_compress_min_save_for_model(model_name: str) -> int:
    """Get compress_min_save value for a given model.

    Currently returns a fixed value; interface reserved for per-provider tuning.

    Args:
        model_name: Model name (e.g. "anthropic/claude-3-opus")

    Returns:
        compress_min_save value (currently fixed at 3000)
    """
    _ = model_name
    return COMPRESS_MIN_SAVE_DEFAULT


@dataclass
class ContextConfig:
    """Context management configuration.

    All thresholds scale dynamically from max_context_tokens using proportional gaps.
    When compress_start_ratio is None (default), the classic fixed ratios apply:
    - proactive_reset_threshold = max_context_tokens * 0.4 (min 20k) — early warning
    - compress_threshold = max_context_tokens * 0.5 (min 25k) — start compression
    - compress_force_threshold = max_context_tokens * 0.7 (min 35k) — force compression
    - summarize_trigger_threshold = max_context_tokens * 0.9 (max window - 20k) — last resort

    When compress_start_ratio is set (range [0.20, 0.85]), thresholds are derived using
    proportional gaps to avoid overflow at any valid ratio:
        gap = (0.95 - compress_start_ratio) / 3
        proactive_reset = compress_start_ratio
        compress = compress_start_ratio + gap
        compress_force = compress_start_ratio + 2 * gap
        summarize_trigger = 0.95 (hard ceiling)

    Note: summarize_trigger_threshold is the hard ceiling; summarization failure raises and aborts.

    Three-layer context defense:
    1. Filter (instant) — truncate large outputs + smart preview
    2. Compress (in-memory) — triggered at compress_threshold, 3-tier strategy (Dedup/Truncate/Remove)
    3. Summarize (irreversible) — triggered at summarize_trigger_threshold, structured summary

    Example:
        config = ContextConfig(max_context_tokens=128000)   # GPT-4 (128k)
        config = ContextConfig(max_context_tokens=200000)   # Claude Sonnet 4.5 (200k)
        config = ContextConfig(max_context_tokens=1000000)  # DeepSeek V4 Pro (1M)
        config = ContextConfig(max_context_tokens=200000, compress_start_ratio=0.6)  # delayed compression
    """

    max_context_tokens: int

    # Optional user-configurable compression start ratio. When set, overrides the
    # default fixed ratios with proportional gap scaling. Valid range: [0.20, 0.85].
    # None means use default ratios (0.4/0.5/0.7/0.9).
    compress_start_ratio: float | None = None

    # Layer 1: single tool result truncation threshold (model-independent)
    tool_result_evict_threshold: int = 5000

    # Layer 1.5: per-turn aggregate tool result threshold (prevents concurrent tools from blowing up)
    turn_aggregate_evict_threshold: int = 15000

    # Minimum compression savings (Prompt Cache protection, model-independent)
    compress_min_save: int = 3000

    # Batch compression: accumulate rounds before flushing (reduces cache break frequency).
    # See CONTEXT_ENGINEERING.md §4.2.
    compress_batch_rounds: int = 5

    # Token budget ratio for tail protection (used in L3 Summarization).
    # Defines the percentage of max_context_tokens to preserve verbatim before compressing.
    tail_budget_ratio: float = 0.20

    # Keep N most recent tool calls in full format (used in L0-L2 Compaction).
    # Protects recent tool outputs from being individually truncated or compacted.
    # Eco mode auto-reduces by 2 (minimum 2).
    keep_recent_calls: int = 5

    # Memory forgetting half-life in days. Frontend can tune the agent's forgetting curve.
    time_decay_half_life_days: float = 90.0

    def _effective_ratio(self) -> float | None:
        """Return clamped compress_start_ratio or None for default behavior."""
        if self.compress_start_ratio is None:
            return None
        return max(0.20, min(0.85, self.compress_start_ratio))

    @property
    def compress_threshold(self) -> int:
        """Compression trigger: 50% of model window (default), or proportional gap from start ratio.

        Acts as the "start water level" for batch compression.
        Pure ratio scaling ensures large-window models (1M+) fully utilize capacity.
        """
        max_tokens = self.max_context_tokens if self.max_context_tokens is not None else 120000
        ratio = self._effective_ratio()
        if ratio is not None:
            gap = (0.95 - ratio) / 3.0
            return max(int(max_tokens * (ratio + gap)), 25000)
        return max(int(max_tokens * 0.5), 25000)

    @property
    def compress_force_threshold(self) -> int:
        """Force compression trigger: 70% of model window (default), or proportional gap.

        Safety valve for batch compression:
        - Within [compress_threshold, compress_force_threshold]: accumulation mode
        - Above compress_force_threshold: immediate forced compression (ignores round count)

        Prevents context explosion, controls API costs, and balances batch efficiency
        with safety protection in extreme cases.
        """
        max_tokens = self.max_context_tokens if self.max_context_tokens is not None else 150000
        ratio = self._effective_ratio()
        if ratio is not None:
            gap = (0.95 - ratio) / 3.0
            return max(int(max_tokens * (ratio + 2 * gap)), 35000)
        return max(int(max_tokens * 0.7), 35000)

    @property
    def proactive_reset_threshold(self) -> int:
        """Proactive reset trigger: 40% of model window (default), or compress_start_ratio.

        Implements Proactive Stage Reset & Compaction. Instead of waiting until the 90%
        error threshold, triggers compression at this healthy watermark to keep the model
        in its optimal clarity zone — mitigating long-conversation degradation, amnesia,
        and hallucination while flattening API token cost from O(n^2) to constant.

        Fires before compress_threshold (50%) as an "early warning" layer.
        """
        max_tokens = self.max_context_tokens if self.max_context_tokens is not None else 120000
        ratio = self._effective_ratio()
        if ratio is not None:
            return max(int(max_tokens * ratio), 20000)
        return max(int(max_tokens * 0.4), 20000)

    @property
    def summarize_trigger_threshold(self) -> int:
        """Summarization trigger (last resort): 95% of window when ratio set, else 90% with reserve.

        Reserves space for the compaction summary itself, ensuring the compaction
        mechanism can run even under maximum context pressure without running out of output space.
        """
        max_tokens = self.max_context_tokens if self.max_context_tokens is not None else 120000
        ratio = self._effective_ratio()
        if ratio is not None:
            return max(int(max_tokens * 0.95), 50000)
        return min(int(max_tokens * 0.9), max(int(max_tokens * 0.5), max_tokens - 20000))


DEFAULT_CONTEXT_CONFIG = ContextConfig(max_context_tokens=128000)


# ============ Tool protection configuration ============
BUILTIN_PROTECTED_TOOLS: frozenset[str] = frozenset(
    {
        "skill_select_tool",
        "planner_tool",
    }
)

DEFAULT_BUSINESS_PROTECTED_TOOLS: set[str] = {
    "memory_search",
}

DEFAULT_SOFT_ONLY_TOOLS: set[str] = {
    "conversation_search_tool",
}

ToolPruneMode = Literal["allow", "soft_only", "protect"]


@dataclass
class ToolProtectionConfig:
    """Tool protection configuration.

    Architecture: built-in + business tool protection.
    - Built-in: framework-level tools (skill_select_tool, planner_tool) are always protected
    - Business: application-level tools (memory_search, etc.) are user-configurable
    - Soft-only: tools that can be trimmed but should not be fully archived
    - Final protected set = built-in tools union business tools

    Cache-TTL pruning uses prune_mode(): protected tools are never touched,
    soft-only tools can retain visible anchors, and the rest may be archived.
    """

    business_protected: set[str] = field(default_factory=lambda: DEFAULT_BUSINESS_PROTECTED_TOOLS.copy())
    soft_only_tools: set[str] = field(default_factory=lambda: DEFAULT_SOFT_ONLY_TOOLS.copy())
    enable_protection: bool = True

    def is_protected(self, tool_name: str) -> bool:
        if not self.enable_protection:
            return False
        return tool_name in BUILTIN_PROTECTED_TOOLS or tool_name in self.business_protected

    def get_all_protected(self) -> set[str]:
        return set(BUILTIN_PROTECTED_TOOLS) | self.business_protected

    def prune_mode(self, tool_name: str) -> ToolPruneMode:
        if self.is_protected(tool_name):
            return "protect"
        if self.enable_protection and tool_name in self.soft_only_tools:
            return "soft_only"
        return "allow"

    def add_business_protection(self, tool_name: str) -> None:
        self.business_protected.add(tool_name)

    def remove_business_protection(self, tool_name: str) -> None:
        self.business_protected.discard(tool_name)

    @classmethod
    def default(cls) -> ToolProtectionConfig:
        return cls()

    @classmethod
    def builtin_only(cls) -> ToolProtectionConfig:
        return cls(business_protected=set())

    @classmethod
    def disabled(cls) -> ToolProtectionConfig:
        return cls(business_protected=set(), soft_only_tools=set(), enable_protection=False)


TOOL_PROTECTION_CONFIG = ToolProtectionConfig.default()


@dataclass(frozen=True, slots=True)
class CacheTtlPruneConfig:
    """Cache-TTL based context pruning configuration.

    When prompt cache TTL expires, old tool results are no longer cached and
    retaining them costs full price. This config controls rule-based pruning
    that trims or archives expired tool results at zero API cost.
    """

    ttl_seconds: float = 300.0
    """Cache TTL in seconds. Default 5min covers Anthropic/Google/DeepSeek."""

    soft_trim_ratio: float = 0.3
    """Context-to-window ratio at which soft trimming begins."""

    hard_clear_ratio: float = 0.5
    """Context-to-window ratio at which offloaded archival pruning begins."""

    keep_last_assistant_turns: int = 3
    """Number of most recent assistant turns whose tool results are protected."""

    min_prunable_tokens: int = 12_500
    """Minimum prunable tokens required to justify processing overhead."""

    soft_trim_head_chars: int = 1500
    """Characters to keep from the beginning of a tool result during soft trim."""

    soft_trim_tail_chars: int = 1500
    """Characters to keep from the end of a tool result during soft trim."""

    max_archives_per_pass: int = 8
    """Maximum archive offloads attempted by one pruning pass."""

    max_offload_bytes_per_pass: int = 2_000_000
    """Maximum original payload bytes offloaded by one pruning pass."""

    max_prune_wall_ms: int = 200
    """Best-effort wall-clock budget for one pruning pass."""

    large_payload_fast_guard_chars: int = 200_000
    """Payload size above which pruning uses bounded estimators and skips full JSON parsing."""

    roi_refetch_ratio_backoff: float = 0.5
    """Refetch ratio at which session-local pruning thresholds are raised."""

    roi_restore_cost_ratio_backoff: float = 0.5
    """Typed restore cost ratio at which session-local pruning thresholds are raised."""

    roi_restore_roi_ratio_backoff: float = 0.5
    """Retained pruning ROI ratio below which session-local pruning thresholds are raised."""

    roi_soft_trim_ratio_bump: float = 0.1
    """Threshold bump applied after poor pruning ROI."""

    roi_backoff_window_size: int = 6
    """Recent cache-TTL prune events evaluated for adaptive ROI backoff."""

    roi_backoff_min_samples: int = 2
    """Minimum recent prune samples required before activating ROI backoff."""

    roi_backoff_recovery_samples: int = 3
    """Healthy recent prune samples required before releasing prior ROI backoff."""

    emergency_prune_ratio: float = 0.92
    """Context ratio at which bounded prune may run during resume/HITL cache preservation."""

    archive_summary_enabled: bool = True
    """Enable background LLM summaries for high-value archived payloads."""

    archive_summary_min_tokens: int = 4_000
    """Minimum original payload tokens required before scheduling an archive summary."""

    archive_summary_max_input_chars: int = 30_000
    """Maximum archive characters sent to the summary LLM."""

    archive_summary_max_queue_size: int = 8
    """Maximum queued/running archive summary jobs per process."""

    archive_summary_max_concurrency: int = 1
    """Maximum concurrent archive summary LLM calls per process."""

    archive_summary_max_tasks_per_chat: int = 2
    """Maximum queued/running archive summary jobs for one chat."""


DEFAULT_CACHE_TTL_PRUNE_CONFIG = CacheTtlPruneConfig()


@dataclass(frozen=True, slots=True)
class CacheUsageFeedback:
    """Provider cache usage feedback used by cache-TTL pruning decisions."""

    calls: int
    input_tokens: int
    cached_tokens: int
    cache_hit_rate: float

    @classmethod
    def from_mapping(cls, value: object) -> CacheUsageFeedback | None:
        if isinstance(value, CacheUsageFeedback):
            return value
        if not isinstance(value, dict):
            return None

        calls = _non_negative_int(value.get("calls"))
        input_tokens = _non_negative_int(value.get("input_tokens"))
        cached_tokens = _non_negative_int(value.get("cached_tokens"))
        cache_hit_rate = _ratio(value.get("cache_hit_rate"))
        if calls == 0 and input_tokens == 0 and cached_tokens == 0 and cache_hit_rate == 0.0:
            return None

        return cls(
            calls=calls,
            input_tokens=input_tokens,
            cached_tokens=cached_tokens,
            cache_hit_rate=cache_hit_rate,
        )

    @classmethod
    def from_flat_metadata(cls, metadata: dict[str, object]) -> CacheUsageFeedback | None:
        """Build feedback at the metadata boundary; processors consume the typed object only."""
        return cls.from_mapping(
            {
                "calls": metadata.get("calls"),
                "input_tokens": metadata.get("input_tokens"),
                "cached_tokens": metadata.get("cached_tokens"),
                "cache_hit_rate": metadata.get("cache_hit_rate"),
            }
        )

    def has_stable_sample(self, *, min_calls: int, min_input_tokens: int) -> bool:
        return self.calls >= min_calls or self.input_tokens >= min_input_tokens


ContextOffloadFailureKind = Literal[
    "temporary_failure",
    "permission_denied",
    "quota_exceeded",
    "unsupported",
]


@dataclass(frozen=True, slots=True)
class ContextOffloadResult:
    """Result of offloading full context content before compression/pruning."""

    path: str = ""
    failure_kind: ContextOffloadFailureKind | None = None
    message: str = ""
    reused: bool = False
    original_bytes: int = 0
    stored_bytes: int = 0

    @property
    def succeeded(self) -> bool:
        return bool(self.path.strip()) and self.failure_kind is None

    @classmethod
    def success(
        cls,
        path: str,
        *,
        reused: bool = False,
        original_bytes: int = 0,
        stored_bytes: int = 0,
    ) -> ContextOffloadResult:
        return cls(
            path=path.strip(),
            reused=reused,
            original_bytes=max(original_bytes, 0),
            stored_bytes=max(stored_bytes, 0),
        )

    @classmethod
    def failure(
        cls,
        failure_kind: ContextOffloadFailureKind,
        message: str = "",
    ) -> ContextOffloadResult:
        return cls(failure_kind=failure_kind, message=message)


def normalize_context_offload_result(value: str | ContextOffloadResult) -> ContextOffloadResult:
    if isinstance(value, ContextOffloadResult):
        return value
    return ContextOffloadResult.success(value) if value.strip() else ContextOffloadResult.failure("temporary_failure")


@dataclass
class CompactToolCall:
    """Compact tool call representation.

    The identifier allows re-execution to recover full information.
    Default: in-memory compression. With ContextCompressOffloadCallback injected,
    original content is persisted to disk and the path is stored in evicted_path.
    """

    tool_name: str
    identifier: str
    identifier_type: Literal["file_path", "url", "query", "code", "other"]
    timestamp: str = ""
    original_tokens: int = 0
    evicted_path: str | None = None


@dataclass
class CompressionIntent:
    """Structured compression focus signal.

    Generated by business layer or control plane as external input for compression planning.
    Used for summary focusing and compression priority: protects failed tool call chains,
    and preserves context for files and modules the current task is focused on.
    """

    focus_files: list[str] = field(default_factory=list)
    focus_modules: list[str] = field(default_factory=list)
    failed_tool_call_ids: list[str] = field(default_factory=list)
    user_goal_hint: str = ""

    @classmethod
    def from_object(cls, value: object) -> CompressionIntent | None:
        if isinstance(value, CompressionIntent):
            return value
        if not isinstance(value, dict):
            return None
        return cls(
            focus_files=[str(item) for item in value.get("focus_files", []) if str(item)],
            focus_modules=[str(item) for item in value.get("focus_modules", []) if str(item)],
            failed_tool_call_ids=[str(item) for item in value.get("failed_tool_call_ids", []) if str(item)],
            user_goal_hint=str(value.get("user_goal_hint", "")).strip(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "focus_files": self.focus_files,
            "focus_modules": self.focus_modules,
            "failed_tool_call_ids": self.failed_tool_call_ids,
            "user_goal_hint": self.user_goal_hint,
        }


@dataclass
class StructuredSummary:
    """Structured summary schema (deterministic output, not free-form).

    Implements a "lossy but traceable" strategy:
    - The summary itself is irreversible — original message structure is replaced
    - But full context is backed up to filesystem (context_dump_path)
    - The model can use grep/cat to retrieve original details

    Handoff fields (inspired by Hermes Context Compaction template):
    - active_task: user's latest unfinished request (verbatim), ensures task continuity
    - constraints_and_preferences: user preferences & constraints, prevents post-compression loss
    - resolved_questions: answered questions, prevents the agent from re-answering
    - pending_user_asks: unfinished requests, prevents omissions
    - active_state: current work state (branch, tests, processes), reduces redundant exploration
    """

    user_goal: str
    completed_actions: list[str] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)
    errors_and_fixes: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    last_action: str = ""
    context_dump_path: str = ""
    active_task: str = ""
    constraints_and_preferences: list[str] = field(default_factory=list)
    resolved_questions: list[str] = field(default_factory=list)
    pending_user_asks: list[str] = field(default_factory=list)
    active_state: str = ""

    def to_json(self) -> str:
        """Serialize to JSON string (for incremental merge prompts)."""
        data: dict[str, object] = {
            "user_goal": self.user_goal,
            "active_task": self.active_task,
            "completed_actions": self.completed_actions,
            "key_findings": self.key_findings,
            "errors_and_fixes": self.errors_and_fixes,
            "files_modified": self.files_modified,
            "last_action": self.last_action,
        }
        if self.constraints_and_preferences:
            data["constraints_and_preferences"] = self.constraints_and_preferences
        if self.resolved_questions:
            data["resolved_questions"] = self.resolved_questions
        if self.pending_user_asks:
            data["pending_user_asks"] = self.pending_user_asks
        if self.active_state:
            data["active_state"] = self.active_state
        return json.dumps(data, ensure_ascii=False, indent=2)


class SummaryPersistCallback(Protocol):
    """Summary persistence callback protocol (dependency inversion).

    Framework layer defines this protocol; business layer injects the implementation.
    After SummarizeProcessor produces a summary, ContextPipelineMiddleware invokes
    this callback to hand the result to the business layer for persistence.

    Typical business implementation: write summary to Chat.compacted_summary and
    before_message_id to Chat.compacted_before_id.
    """

    def __call__(
        self,
        chat_id: str,
        summary: StructuredSummary,
        before_message_id: str,
        tokens_saved: int,
    ) -> Coroutine[object, object, None]: ...


class ContextCompressOffloadCallback(Protocol):
    """Full tool result offload callback (dependency inversion).

    Called before compression or cache-TTL pruning converts a ToolMessage into a
    compact/restorable reference. The scope is a framework-neutral isolation key;
    business identity such as user/account IDs must stay outside this callback.
    On error or empty return, callers must degrade without irreversible data loss.
    """

    def __call__(
        self, *, content: str, tool_name: str, scope_id: str | None
    ) -> Coroutine[object, object, str | ContextOffloadResult]: ...


def _non_negative_int(value: object) -> int:
    return max(int(value), 0) if isinstance(value, (int, float)) else 0


def _ratio(value: object) -> float:
    if not isinstance(value, (int, float)):
        return 0.0
    return min(max(float(value), 0.0), 1.0)


@dataclass
class EvictedToolCall:
    """Evicted tool call data, containing original uncompressed content.

    Attributes:
        ai_msg: The AI message that initiated the tool call
        tool_msg: Tool response message (compressed reference, used only for metadata like name)
        original_content: Original tool output content before compression
    """

    ai_msg: BaseMessage
    tool_msg: BaseMessage
    original_content: str


class ContextCompressEvictionCallback(Protocol):
    """Compression eviction callback protocol (dependency inversion).

    Triggered when tool calls are truncated/compressed (evicted from full context).
    Can be used to implement Zero-cost Memory Extraction Boundary and similar logic.
    """

    def __call__(
        self, evicted_pairs: list[EvictedToolCall], user_goal_hint: str
    ) -> Coroutine[object, object, None]: ...


class ContextSnapshotCallback(Protocol):
    """Pre-compression full message snapshot callback (dependency inversion).

    Called before compression triggers, serializing complete messages to a sanitized+gzipped
    JSONL snapshot file. Symmetric design with ContextCompressOffloadCallback: framework
    defines protocol, business layer injects implementation.
    On error or empty return, compression continues (degrades to no-snapshot mode).

    Returns:
        Workspace-relative path to the snapshot file, or empty string on failure.
    """

    def __call__(
        self, *, messages: list[BaseMessage], chat_id: str | None, user_id: str | None
    ) -> Coroutine[object, object, str]: ...


@dataclass(frozen=True, slots=True)
class PreCompactInjection:
    """Result of a pre-compaction semantic memory recall."""

    message: BaseMessage
    recalled_ids: tuple[str, ...]
    token_estimate: int
    query: str
    compaction_tier: str


class ContextPreCompactCallback(Protocol):
    """Pre-compaction memory recall callback (dependency inversion).

    Invoked before Compress / SessionNotes / Summarize mutates the message list.
    Returns injection content to prepend into the protected compaction zone, or None to skip.
    """

    def __call__(
        self,
        *,
        messages: list[BaseMessage],
        chat_id: str | None,
        user_id: str | None,
        compaction_tier: str,
        token_pressure_ratio: float,
        user_goal_hint: str,
    ) -> Coroutine[object, object, PreCompactInjection | None]: ...


PRE_COMPACT_MESSAGE_METADATA_KEY = "pre_compact_message"
PRE_COMPACT_INJECTION_METADATA_KEY = "pre_compact_injection"

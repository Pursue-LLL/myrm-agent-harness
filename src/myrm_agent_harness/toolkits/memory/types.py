"""Memory type definitions — enums and Pydantic schemas.

Zero ORM or backend dependencies. This is the foundation layer that
all other memory modules depend on.

[INPUT]
- pydantic::BaseModel (POS: Validation + serialization layer)
- datetime, uuid (POS: Standard library utilities)

[OUTPUT]
- MemoryType: Enum for memory classification (PROFILE/SEMANTIC/EPISODIC/CONVERSATION/PROCEDURAL/CLAIM/TASK_DIGEST/INTEGRATION)
- MemoryStatus: Unified lifecycle status enum (ACTIVE/DISABLED/ARCHIVED)
- MemoryMutationRef, MemoryMutationResult: Exact mutation outcome DTOs for audited delete/rollback flows
- BaseMemory: Base class for all memory types (includes status field)
- ProfileEntry: User profile key-value pairs
- SemanticMemory: Extracted knowledge from conversations
- EpisodicMemory: Timestamped events with entities
- ConversationMemory: Verbatim conversation exchanges (dual-field: raw + summary, dual-embedding: precision + coverage)
- ProceduralMemory: If-then rules for agent behavior
- PendingRecord: Approval queue entry

[POS]
Memory type system foundation. Provides type-safe schema definitions for all
memory types. ConversationMemory implements verbatim storage with dual-field
(raw_exchange + content summary) and dual-embedding (raw + summary vectors)
for lossless information preservation and adaptive retrieval optimization.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

# ── Enums ───────────────────────────────────────────────────────────


class MemoryType(StrEnum):
    PROFILE = "profile"
    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    CONVERSATION = "conversation"
    PROCEDURAL = "procedural"
    CLAIM = "claim"
    TASK_DIGEST = "task_digest"
    INTEGRATION = "integration"


class RuleSource(StrEnum):
    USER_EXTRACTED = "user_extracted"
    AGENT_SELF = "agent_self"
    USER_EXPLICIT = "user_explicit"


class MemoryTier(StrEnum):
    L1 = "l1"
    L2 = "l2"
    L3 = "l3"


class DigestKind(StrEnum):
    TASK = "task"


class EvaporationState(StrEnum):
    PENDING = "pending"
    EVAPORATED = "evaporated"


class ClaimGraphState(StrEnum):
    PENDING = "pending"
    COMPILED = "compiled"


class ClaimConflictState(StrEnum):
    NONE = "none"
    CONFLICTED = "conflicted"


class ConflictResolution(StrEnum):
    """Resolution action for a detected memory contradiction.

    Used by the consolidation conflict callback to communicate
    the user's decision back to the framework.
    """

    KEEP_OLD = "keep_old"
    KEEP_NEW = "keep_new"
    MERGE = "merge"
    DISCARD_BOTH = "discard_both"
    PENDING = "pending"


class ToolRulePriority(StrEnum):
    """Priority level for tool-scoped procedural rules.

    CRITICAL rules are pinned into the system prompt and immune to
    context compression. HIGH rules are included when budget permits.
    NORMAL rules are injected only when the associated tool is active.
    """

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"


class MemoryStatus(StrEnum):
    """Unified status for all memory types.

    Replaces the legacy ProceduralMemory.is_active bool and
    metadata["archived"] hack with a single type-safe enum.
    """

    ACTIVE = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class MemoryMutationRef(BaseModel):
    """A single typed memory mutation outcome reference."""

    memory_type: str
    memory_id: str
    backend: str
    reason: str = ""


class MemoryMutationResult(BaseModel):
    """Exact outcome of a typed memory mutation request."""

    deleted_refs: list[MemoryMutationRef] = Field(default_factory=list)
    missing_refs: list[MemoryMutationRef] = Field(default_factory=list)
    forbidden_refs: list[MemoryMutationRef] = Field(default_factory=list)
    failed_refs: list[MemoryMutationRef] = Field(default_factory=list)

    def deleted_counts_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for ref in self.deleted_refs:
            counts[ref.memory_type] = counts.get(ref.memory_type, 0) + 1
        return counts


class ProfileAttributeSnapshot(BaseModel):
    """Content-local profile attribute value and revision."""

    key: str
    value: str | None = None
    exists: bool = False
    revision: str = ""
    updated_at: datetime | None = None


# ── Base ────────────────────────────────────────────────────────────


class MemoryScope(BaseModel):
    """Deterministic ownership and session identity for a memory record.

    ``namespaces`` is the search-facing scope list. It is ordered from broader
    to narrower scopes and is used by the vector layer for namespace-aware
    retrieval. ``primary_namespace`` is a stable audit label for the memory's
    effective bucket.
    """

    primary_namespace: str = ""
    namespaces: list[str] = Field(default_factory=list)
    agent_id: str | None = None
    channel_id: str | None = None
    conversation_id: str | None = None
    task_id: str | None = None


class MemoryLifecycle(BaseModel):
    """Typed lifecycle state for compiled / staged memories.

    This model replaces ad-hoc metadata strings for tiered memory flows such as
    task digests and claim graph compilation.
    """

    tier: MemoryTier
    digest_kind: DigestKind | None = None
    evaporation_state: EvaporationState | None = None
    evaporated_at: datetime | None = None
    claim_graph_state: ClaimGraphState | None = None
    claim_graph_node_id: str | None = None
    claim_graph_updated_at: datetime | None = None
    claim_graph_conflict: ClaimConflictState | None = None

    @field_validator("evaporated_at", "claim_graph_updated_at", mode="before")
    @classmethod
    def _ensure_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v

    @classmethod
    def new_task_digest(cls) -> MemoryLifecycle:
        return cls(
            tier=MemoryTier.L2,
            digest_kind=DigestKind.TASK,
            evaporation_state=EvaporationState.PENDING,
            claim_graph_state=ClaimGraphState.PENDING,
            claim_graph_conflict=ClaimConflictState.NONE,
        )


class BaseMemory(BaseModel):
    """Common fields shared by all memory types.

    Sharing is represented by ``scope.namespaces`` rather than business-specific
    fields. Product layers can bind their own concepts to framework-safe
    namespace strings, e.g. ``shared:customer-a``.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str = Field(..., description="Memory text content")
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    access_count: int = Field(default=0)
    last_accessed_at: datetime | None = None
    user_rating: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="User feedback rating [0,1]. 0.5 = neutral (no feedback yet). Updated via EMA.",
    )
    pinned: bool = Field(default=False, description="User-pinned: immune to forgetting")
    expected_valid_days: int | None = Field(
        default=None,
        description="LLM-estimated validity window in days. None = use global half-life fallback.",
    )
    status: MemoryStatus = Field(default=MemoryStatus.ACTIVE, description="Unified lifecycle status")
    scope: MemoryScope = Field(default_factory=MemoryScope)
    lifecycle: MemoryLifecycle | None = None

    @field_validator("created_at", "updated_at", "last_accessed_at", mode="before")
    @classmethod
    def _ensure_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


# ── Concrete types ──────────────────────────────────────────────────


class ProfileEntry(BaseModel):
    """A single user-profile attribute (key-value pair).

    Attributes:
        language: Primary language of the value content ("zh" or "en")
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    key: str
    value: str | int | float | bool | list[str] | dict[str, str] = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    language: Literal["zh", "en"] = "en"
    scope: MemoryScope = Field(default_factory=MemoryScope)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _ensure_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


PreferenceType = Literal["explicit", "implicit"]


class SemanticMemory(BaseMemory):
    """Factual knowledge stored with vector embeddings.

    Preference-bearing memories additionally carry ``preference_type``
    and ``preference_strength`` so the RRF retriever can boost them
    automatically without a separate search path.

    Attributes:
        language: Primary language of the content ("zh" or "en")
        merge_count: Number of times this memory has been merged/updated
        merge_history: Compact text log of merge operations
    """

    memory_type: Literal[MemoryType.SEMANTIC] = MemoryType.SEMANTIC
    embedding: list[float] | None = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_chat_id: str | None = None
    source_message_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    preference_type: PreferenceType | None = None
    preference_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    correction_of: str | None = Field(
        default=None, description="ID of the memory this one corrects, forming a correction chain"
    )
    source_error: str | None = Field(
        default=None, description="Description of the mistake being corrected (complements correction_of)"
    )
    language: Literal["zh", "en"] = "en"
    merge_count: int = Field(default=0, ge=0, description="Number of merges applied to this memory")
    merge_history: str = Field(default="", description="Compact merge log: timestamp|action|summary")


class EpisodicMemory(BaseMemory):
    """Conversation event stored with vector embeddings and optional graph.

    Attributes:
        language: Primary language of the content ("zh" or "en")
        merge_count: Number of times this memory has been merged/updated
        merge_history: Compact text log of merge operations
    """

    memory_type: Literal[MemoryType.EPISODIC] = MemoryType.EPISODIC
    embedding: list[float] | None = None
    event_type: str = "conversation"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    related_entities: list[str] = Field(default_factory=list)
    source_chat_id: str | None = None
    source_message_id: str | None = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    language: Literal["zh", "en"] = "en"
    merge_count: int = Field(default=0, ge=0, description="Number of merges applied to this memory")
    merge_history: str = Field(default="", description="Compact merge log: timestamp|action|summary")


class ConversationMemory(BaseMemory):
    """Conversation exchange stored with dual-field verbatim + summary.

    Dual-field storage prevents irreversible information loss:
    - raw_exchange: User question + AI response verbatim (no LLM processing)
    - content: LLM-extracted summary for context compression

    Dual-embedding enables precision + coverage trade-off:
    - raw_embedding: Embedding of raw_exchange (high precision)
    - summary_embedding: Embedding of content (broad coverage)

    Attributes:
        raw_exchange: Verbatim Q+A pair, never modified
        content: LLM extracted summary
        raw_embedding: Vector embedding of raw_exchange
        summary_embedding: Vector embedding of content
        timestamp: When this exchange occurred
        user_turn_only: Whether only user turns are indexed (default True)
        related_entities: Entities mentioned in conversation
        project_id: Project/wing hierarchy (optional)
        topic_id: Topic/room hierarchy (optional)
        language: Primary language ("zh" or "en")
    """

    memory_type: Literal[MemoryType.CONVERSATION] = MemoryType.CONVERSATION
    raw_exchange: str = Field(..., description="User Q + AI A verbatim text")
    raw_embedding: list[float] | None = None
    summary_embedding: list[float] | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    user_turn_only: bool = Field(
        default=True, description="Index only user turns (MemPalace strategy for 96.6% baseline)"
    )
    related_entities: list[str] = Field(default_factory=list)
    source_chat_id: str | None = None
    source_message_id: str | None = None
    project_id: str | None = Field(default=None, description="Project/wing identifier")
    topic_id: str | None = Field(default=None, description="Topic/room identifier")
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    language: Literal["zh", "en"] = "en"

    def without_raw(self) -> ConversationMemory:
        """Return copy without raw_exchange (for lazy loading)."""
        return self.model_copy(update={"raw_exchange": "", "raw_embedding": None})

    @property
    def display_content(self) -> str:
        """Return summary content for display (not raw verbatim)."""
        return self.content


class EpisodicRelation(BaseModel):
    """Directed relation between two episodic memories (graph edge)."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    source_memory_id: str
    target_memory_id: str
    relation_type: str
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProceduralMemory(BaseMemory):
    """Behavioral rule: trigger -> action.

    ``is_active`` is kept for SQLite column compatibility but derives from
    ``status``. Prefer using ``status`` for new code.

    Tool-scoped rules use ``tool_name`` to associate with a specific tool
    and ``tool_rule_priority`` to control compression resistance:
    - CRITICAL: pinned into system prompt, immune to compression
    - HIGH: included when budget permits
    - NORMAL: injected only when the associated tool is active

    Attributes:
        language: Primary language of the rule content ("zh" or "en")
        tool_name: Tool this rule is scoped to (None = global rule)
        tool_rule_priority: Compression resistance level for tool-scoped rules
    """

    memory_type: Literal[MemoryType.PROCEDURAL] = MemoryType.PROCEDURAL
    trigger: str
    action: str
    reasoning: str = Field(default="", description="Why this rule exists (Context/Rationale)")
    application: str = Field(default="", description="How to apply this rule (Nuances/Boundaries)")
    priority: int = 0
    is_active: bool = Field(default=True, description="Derived from status on save")
    trigger_keywords: list[str] = Field(default_factory=list)
    source: RuleSource = RuleSource.USER_EXTRACTED
    language: Literal["zh", "en"] = "en"
    tool_name: str | None = Field(default=None, description="Tool this rule is scoped to (None = global)")
    tool_rule_priority: ToolRulePriority = Field(
        default=ToolRulePriority.NORMAL,
        description="Compression resistance: CRITICAL rules are pinned into system prompt",
    )
    is_user_locked: bool = Field(
        default=False,
        description="User-edited rules are locked against background consolidation/forgetting overwrites",
    )

    def model_post_init(self, __context: object) -> None:
        """Sync is_active ↔ status on construction for legacy data."""
        if not self.is_active and self.status == MemoryStatus.ACTIVE:
            self.status = MemoryStatus.DISABLED
        elif self.is_active and self.status == MemoryStatus.DISABLED:
            self.is_active = False


class ClaimMemory(BaseMemory):
    """Compiled knowledge object produced from the claim graph.

    ClaimMemory is retrieval-only: it represents L3 compiled knowledge and must
    not be treated as a regular semantic fact written through vector storage.
    """

    memory_type: Literal[MemoryType.CLAIM] = MemoryType.CLAIM
    claim_key: str
    title: str
    claim_text: str
    model_summary: str = ""
    last_result: str = ""
    evidence_count: int = Field(default=0, ge=0)
    freshness: str = "stale"
    freshness_days: int = Field(default=0, ge=0)
    contradiction_status: str = "none"
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)


class IntegrationMemory(BaseMemory):
    """External service data cached as local memory for semantic retrieval.

    Integration memories are populated by pulling data from third-party services
    (Gmail, GitHub, Slack, Notion, etc.) and indexing it locally. This enables
    cross-source semantic retrieval without live API calls.
    """

    memory_type: Literal[MemoryType.INTEGRATION] = MemoryType.INTEGRATION
    embedding: list[float] | None = None
    provider: str = Field(..., description="Integration source identifier (e.g. 'gmail', 'github')")
    account_key: str = Field(default="", description="Stable account identifier within the provider")
    account_label: str = Field(default="", description="Human-readable account label")
    source_type: str = Field(default="", description="Object type within the provider (e.g. 'email', 'pr')")
    external_object_id: str | None = Field(default=None, description="Provider-side unique object ID")
    external_object_type: str | None = Field(default=None, description="Provider-side object type label")
    title: str = Field(default="", description="Human-readable title")
    summary: str = Field(default="", description="Compact summary for tree aggregation")
    tags: list[str] = Field(default_factory=list)
    observed_at: datetime | None = Field(default=None, description="When this data was originally observed")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    tree_id: str = Field(default="", description="ID of the integration tree this leaf belongs to")
    importance: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("observed_at", mode="before")
    @classmethod
    def _ensure_observed_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


# ── Search result ───────────────────────────────────────────────────


class MemorySearchResult(BaseModel):
    """Search result with relevance score."""

    memory: SemanticMemory | EpisodicMemory | ConversationMemory | ProceduralMemory | ClaimMemory | IntegrationMemory
    score: float = Field(ge=0.0, le=1.0)
    memory_type: MemoryType

    @property
    def id(self) -> str:
        return self.memory.id

    @property
    def content(self) -> str:
        return self.memory.content


# ── Pending record ──────────────────────────────────────────────────


class PendingRecord(BaseModel):
    """A memory awaiting user approval or conflict resolution.

    Stores the original memory object as JSON so it can be fully
    reconstructed on approval without information loss.
    When ``is_conflict`` is True, the record represents a detected memory
    contradiction that requires user arbitration before automatic merging.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    memory_type: MemoryType
    content: str
    memory_data: dict[str, object] = Field(
        default_factory=dict, description="Serialised AnyMemory fields for lossless reconstruction"
    )
    source_chat_id: str | None = None
    source_message_id: str | None = None
    status: Literal["pending", "approved", "rejected", "resolved"] = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None

    is_conflict: bool = False
    conflict_old_memory_id: str | None = None
    conflict_old_content: str | None = None
    conflict_accuracy_score: float | None = None
    conflict_importance: float | None = None
    conflict_auto_resolve_at: datetime | None = None


# ── Type aliases ────────────────────────────────────────────────────

AnyMemory = SemanticMemory | EpisodicMemory | ConversationMemory | ProceduralMemory | IntegrationMemory

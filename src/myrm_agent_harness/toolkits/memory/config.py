"""Memory configuration — functional switches and retrieval params only.

[INPUT]
- (none)

[OUTPUT]
- AdaptiveThresholdStrategy: Protocol for adaptive similarity threshold strategies.
- CountBasedThresholdStrategy: Count-based adaptive threshold strategy with smooth trans...
- RecallMode: Controls how memory context is delivered to the agent.
- MemoryScopeLevel: Typed namespace levels for agent memory policy.
- MemoryWritePolicy: Write target for agent-bound memory managers.

[POS]
Memory configuration — functional switches and retrieval params only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from myrm_agent_harness.toolkits.memory._internal.hash_utils import NormalizationLevel
from myrm_agent_harness.toolkits.memory.strategies.forgetting import ForgettingConfig
from myrm_agent_harness.toolkits.memory.types import MemoryType

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.adaptive import AdaptiveChannelStrategy
    from myrm_agent_harness.toolkits.memory.archival import ArchivalStrategy
    from myrm_agent_harness.toolkits.memory.intent_recognizers import (
        QueryIntentRecognizer,
    )


class AdaptiveThresholdStrategy(Protocol):
    """Protocol for adaptive similarity threshold strategies.

    Allows dynamic threshold adjustment based on memory count to:
    - Lower thresholds for small libraries (improve recall)
    - Raise thresholds for large libraries (reduce noise)
    """

    def get_threshold(self, memory_count: int) -> float:
        """Get adaptive similarity threshold based on memory count.

        Args:
            memory_count: Total number of memories in the library

        Returns:
            Similarity threshold value (typically in range [0.4, 0.65])
        """
        ...


def _normalize_model_name(model: str) -> str:
    """Normalize embedding model name into a collection-name-safe suffix.

    Qdrant collection names allow alphanumerics, hyphens, and underscores.
    Model names like "openai/BAAI/bge-m3" become "openai-baai-bge-m3".
    """
    return re.sub(r"[^a-zA-Z0-9]+", "-", model).strip("-").lower()[:40]


class CountBasedThresholdStrategy:
    """Count-based adaptive threshold strategy with smooth transitions.

    Threshold ranges:
    - <500 memories: 0.45 (small library, improve recall)
    - 500-2000: 0.50 (medium library, default BGE-M3 optimized)
    - 2000-5000: 0.55 (large library, reduce noise)
    - >5000: 0.60 (very large library, strict filtering)

    Uses smooth linear interpolation between thresholds to avoid sudden jumps.
    """

    def get_threshold(self, memory_count: int) -> float:
        """Calculate adaptive threshold with smooth transitions."""
        if memory_count < 500:
            return 0.45
        elif memory_count < 2000:
            ratio = (memory_count - 500) / (2000 - 500)
            return 0.45 + (0.50 - 0.45) * ratio
        elif memory_count < 5000:
            ratio = (memory_count - 2000) / (5000 - 2000)
            return 0.50 + (0.55 - 0.50) * ratio
        else:
            ratio = min((memory_count - 5000) / 5000, 1.0)
            return 0.55 + (0.60 - 0.55) * ratio


class RecallMode(StrEnum):
    """Controls how memory context is delivered to the agent.

    - HYBRID: context injection + memory tools (default, full capability)
    - CONTEXT: context injection only, memory tools hidden (API/headless scenarios)
    - TOOLS: memory tools only, no auto-injection (minimal token overhead)
    """

    HYBRID = "hybrid"
    CONTEXT = "context"
    TOOLS = "tools"


class MemoryScopeLevel(StrEnum):
    """Typed namespace levels for agent memory policy."""

    GLOBAL = "global"
    AGENT = "agent"
    CHANNEL = "channel"
    CONVERSATION = "conversation"
    TASK = "task"


class MemoryWritePolicy(StrEnum):
    """Write target for agent-bound memory managers."""

    INHERIT = "inherit"
    GLOBAL = "global"
    AGENT = "agent"
    CHANNEL = "channel"
    CONVERSATION = "conversation"
    TASK = "task"


@dataclass(frozen=True, slots=True)
class AgentMemoryPolicy:
    """Formal read/write boundary for an agent-bound memory manager.

    ``read_scopes`` controls which namespaces are visible during retrieval.
    ``write_policy`` controls where newly written private memories land.

    - ``INHERIT`` preserves existing behavior: write with the full derived scope chain.
    - Explicit write levels narrow writes to a single namespace, e.g. task-only.
    """

    agent_id: str | None = None
    channel_id: str | None = None
    conversation_id: str | None = None
    task_id: str | None = None
    read_scopes: tuple[MemoryScopeLevel, ...] | None = None
    write_policy: MemoryWritePolicy = MemoryWritePolicy.INHERIT


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    """Retrieval scoring configuration.

    Attributes:
        rrf_k: RRF constant (higher = more uniform distribution)
        type_weights: Memory type weights for RRF fusion
        correction_penalty: Penalty multiplier for corrected memories
        frequency_saturation: Access count at which frequency factor reaches 1.0
        mmr_lambda: MMR diversity balance (1.0 = pure relevance, 0.0 = pure diversity)
        enable_conversation_raw_channel: Enable raw_embedding channel for ConversationMemory
        raw_channel_weight: Weight for raw_embedding channel (summary_channel_weight = 1 - this)
        keyword_overlap_weight: Keyword overlap boost weight (MemPalace hybrid enhancement)
        keyword_overlap_min_tokens: Minimum token overlap to apply boost
        enable_adaptive_channel: Enable adaptive dual-channel selection (saves ~35% query cost)
        adaptive_threshold: Token count threshold for dual-channel (queries < threshold use summary only)
        adaptive_diversity_threshold: Word diversity ratio threshold (unique_words/total_words)
        adaptive_strategy: Optional custom strategy for adaptive channel selection (overrides default 3-factor logic)
        enable_two_pass_assistant_retrieval: Enable Two-Pass for assistant-reference queries (MemPalace enhancement)
        two_pass_first_stage_limit: Pass 1 top-K sessions to consider in Pass 2
        enable_keyword_boost: Enable keyword overlap boost in ResultBooster
        keyword_boost_weight: Keyword boost weight (multiplicative factor)
        enable_temporal_boost: Enable temporal proximity boost in ResultBooster
        temporal_boost_max_weight: Maximum temporal boost weight (for same-day matches)
        enable_person_name_boost: Enable person name match boost in ResultBooster
        person_name_boost_weight: Person name boost weight (multiplicative factor)
        enable_quoted_phrase_boost: Enable quoted phrase match boost in ResultBooster
        quoted_phrase_boost_weight: Quoted phrase boost weight (multiplicative factor)
        enable_preference_boost: Enable preference boost for preference-tagged memories (MemPalace enhancement)
        preference_boost_weight: Preference boost weight (multiplicative factor, applied to preference_strength)
    """

    rrf_k: int = 60
    type_weights: dict[MemoryType, float] = field(
        default_factory=lambda: {
            MemoryType.PROFILE: 1.0,
            MemoryType.SEMANTIC: 1.0,
            MemoryType.EPISODIC: 0.8,
            MemoryType.CONVERSATION: 0.95,
            MemoryType.PROCEDURAL: 0.9,
            MemoryType.CLAIM: 1.05,
        }
    )
    correction_penalty: float = 0.1
    frequency_saturation: int = 50
    mmr_lambda: float = 0.7
    enable_conversation_raw_channel: bool = True
    raw_channel_weight: float = 0.4
    keyword_overlap_weight: float = 0.15
    keyword_overlap_min_tokens: int = 2
    temporal_boost_weight: float = 0.40
    temporal_boost_threshold_hours: float = 24.0
    quoted_phrase_boost: float = 1.5
    person_name_boost: float = 0.67
    preference_min_confidence: float = 0.7
    enable_adaptive_channel: bool = True
    adaptive_threshold: int = 5
    adaptive_diversity_threshold: float = 0.7
    adaptive_strategy: AdaptiveChannelStrategy | None = None
    enable_two_pass_assistant_retrieval: bool = True
    two_pass_first_stage_limit: int = 10
    enable_keyword_boost: bool = True
    keyword_boost_weight: float = 0.30
    enable_temporal_boost: bool = True
    temporal_boost_max_weight: float = 0.40
    enable_person_name_boost: bool = True
    person_name_boost_weight: float = 0.20
    enable_quoted_phrase_boost: bool = True
    quoted_phrase_boost_weight: float = 0.25
    enable_preference_boost: bool = True
    preference_boost_weight: float = 0.15
    source_diversity_weight: float = 0.5
    """Source diversity penalty weight for MMR session diversification.
    Controls how much to penalize results from already-selected source sessions.
    0.0 = disabled (pure content MMR), 1.0 = strong source diversification."""
    enable_intent_recognition: bool = True
    intent_recognizer: QueryIntentRecognizer | None = None


@dataclass(frozen=True, slots=True)
class DeduplicationParams:
    """Three-layer deduplication parameters.

    Attributes:
        enabled: Enable smart deduplication (requires LLM)
        high_threshold: Similarity ≥ this → obvious duplicate
        low_threshold: Similarity < this → obviously new
        time_window_hours: Recent window for stricter judgment
        hash_cache_capacity: Maximum number of content hashes to keep in memory (FIFO eviction)
        normalization_level: Hash normalization strategy (NONE/BASIC/FULL)
        adaptive_capacity: Enable adaptive capacity management (auto-adjusts based on memory count)
        capacity_multiplier: Target cache size = memory_count * multiplier (when adaptive enabled)
        persist_hash_cache: Enable hash cache persistence to disk for cross-instance deduplication
        hash_cache_path: Path to persist hash cache (defaults to ~/.cache/myrm/hash_cache.json)
        warmup_cache: Enable embedding cache warmup on initialization (preloads recent memories)
        warmup_limit: Number of recent memories to preload into embedding cache
    """

    enabled: bool = True
    high_threshold: float = 0.95
    low_threshold: float = 0.60
    time_window_hours: int = 24
    hash_cache_capacity: int = 10000
    normalization_level: NormalizationLevel = NormalizationLevel.FULL
    adaptive_capacity: bool = True
    capacity_multiplier: float = 1.5
    persist_hash_cache: bool = False
    hash_cache_path: str = ""
    warmup_cache: bool = True
    warmup_limit: int = 100


@dataclass(frozen=True, slots=True)
class ConsolidationConfig:
    """Cross-session memory consolidation configuration.

    Attributes:
        enabled: Enable periodic memory consolidation (requires consolidation_llm)
        interval_hours: Minimum hours between consolidation runs
        max_memories: Maximum memories to process per consolidation run
        soft_lock_hours: Skip if consolidated within this many hours (concurrency guard)
        enrich_max_similar: Max similar memories to fetch when only 1 new memory exists
        conflict_importance_threshold: Minimum importance to route a contradiction to user review
        conflict_confidence_threshold: Route to user when LLM accuracy is below this value
        conflict_auto_resolve_days: Days before an unresolved conflict auto-resolves as keep_new
    """

    enabled: bool = True
    interval_hours: int = 24
    max_memories: int = 100
    soft_lock_hours: float = 1.0
    enrich_max_similar: int = 3
    message_count_trigger: int = 50
    conflict_importance_threshold: float = 0.6
    conflict_confidence_threshold: float = 0.85
    conflict_auto_resolve_days: int = 7


@dataclass(frozen=True, slots=True)
class RecurrenceConfig:
    """Recurrence-triggered memory consolidation configuration.

    Detects topics that appear repeatedly across sessions via embedding similarity,
    then triggers LLM refinement to produce high-quality long-term memories.

    Attributes:
        enabled: Enable recurrence detection on session end
        similarity_threshold: Cosine similarity threshold to consider two sessions as covering the same topic
        recurrence_k: Number of recurrences needed to trigger consolidation
        buffer_capacity: Maximum entries in the recurrence buffer (excess evicted when over capacity)
        importance_preemption: Bypass recurrence counting for safety/health/identity signals
    """

    enabled: bool = True
    similarity_threshold: float = 0.70
    recurrence_k: int = 4
    buffer_capacity: int = 200
    importance_preemption: bool = True


@dataclass(frozen=True, slots=True)
class ArchivalConfig:
    """Memory archival configuration.

    Archival system moves old, rarely-accessed memories to separate collections
    to improve search performance while preserving historical data.
    """

    enabled: bool = True
    archival_strategy: ArchivalStrategy | None = None
    auto_archive_interval_hours: int = 168
    """Auto-archival interval (default: 168h / 7 days)."""
    min_age_days: float = 180.0
    """Minimum memory age for archival eligibility (default: 180 days / 6 months)."""
    max_access_count: int = 5
    """Maximum access count for archival (default: 5 times)."""
    max_importance: float = 0.3
    """Maximum importance for archival (default: 0.3 / low priority)."""
    batch_size: int = 100
    """Maximum memories to archive per operation (default: 100)."""


@dataclass(frozen=True, slots=True)
class MemoryConfig:
    """Memory system configuration.

    Hybrid retrieval strategy:
    - Vector search: semantic similarity matching
    - BM25 search: keyword/proper noun matching (auto-enabled, degrades when >5000 memories)
    - RRF fusion: combines both channels for optimal recall

    BM25 parameters:
    - bm25_top_k: Number of BM25 results to retrieve for RRF fusion
    - bm25_max_corpus_size: Auto-degradation threshold (disables BM25 when exceeded)

    Deduplication:
    - dedup: Three-layer smart deduplication configuration

    Context injection:
    - max_learned_context_chars: Budget for auto-injected learned memories (preferences + rules)

    Consolidation:
    - consolidation: Cross-session memory consolidation (dream mechanism)

    Recurrence:
    - recurrence: Recurrence-triggered consolidation (sleep-like topic detection)
    """

    embedding_model: str
    collection_prefix: str = "memory"
    default_search_limit: int = 10
    similarity_threshold: float = 0.5
    enable_adaptive_threshold: bool = True
    adaptive_threshold_strategy: AdaptiveThresholdStrategy = field(default_factory=CountBasedThresholdStrategy)
    forgetting_interval: int = 10
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    bm25_top_k: int = 50
    bm25_max_corpus_size: int = 5000
    dedup: DeduplicationParams = field(default_factory=DeduplicationParams)
    max_learned_context_chars: int = 2000
    max_corrections: int = 10
    """Maximum correction memories to inject. Corrections are prioritized over
    preferences and capped to prevent stale corrections from flooding context."""
    model_context_tokens: int | None = None
    """Model's total context window in tokens. When set, learned context budget
    scales as max(max_learned_context_chars, model_context_tokens // 30)."""
    consolidation: ConsolidationConfig = field(default_factory=ConsolidationConfig)
    recurrence: RecurrenceConfig = field(default_factory=RecurrenceConfig)
    forgetting: ForgettingConfig = field(default_factory=ForgettingConfig)
    archival: ArchivalConfig = field(default_factory=ArchivalConfig)
    rating_alpha: float = 0.3
    """EMA smoothing factor for positive user_rating updates (normalized >= old_rating).
    Formula: rating_new = rating_old + alpha * (normalized_score - rating_old)"""
    rating_alpha_negative: float = 0.5
    """EMA smoothing factor for negative user_rating updates (normalized < old_rating).
    Asymmetric by design: negative feedback causes faster rating decay, requiring
    more positive validations to recover trust. Inspired by loss-aversion bias."""
    security_scan_enabled: bool = True
    """Scan memory content for injection/credential/invisible-unicode before persistence."""
    injection_block_threshold: float = 0.8
    """Prompt injection score >= this value blocks the memory write entirely.
    SaaS deployments may lower to 0.7 for stricter protection."""
    neglect_importance_threshold: float = 0.6
    """Importance threshold for neglected-memory detection during maintenance."""
    neglect_stale_days: int = 14
    """Days since last access to consider a high-importance memory as neglected."""
    neglect_max_items: int = 10
    """Maximum number of neglected memories to report per maintenance cycle."""
    blob_storage_enabled: bool = True
    """Enable transparent external BLOB storage for large raw_exchange payloads."""
    blob_storage_threshold: int = 4096
    """Minimum size in bytes to trigger external BLOB storage (default 4KB)."""
    blob_storage_path: str = "~/.myrm/blobs"
    """Directory path for external BLOB storage."""
    graph_sibling_limit: int = 10
    """Maximum number of graph siblings to retrieve during enrichment."""
    graph_max_depth: int = 2
    """Maximum graph traversal depth for multi-hop discovery (1=direct only, 2=two-hop)."""
    graph_distance_decay: float = 0.5
    """Score decay factor per hop depth. depth=1 gets base score, depth=2 gets base*decay."""

    auto_session_recall_enabled: bool = True
    """Enable automatic first-turn historical conversation recall.
    When enabled, the middleware searches conversation/task_digest memories on the first
    user message and injects high-confidence results before the Agent reasons."""
    auto_session_recall_threshold: float = 0.72
    """Minimum RRF score to inject a recalled memory. Higher = fewer but more precise results.
    Range: [0.5, 0.95]. Default 0.72 is conservative — prefers precision over recall."""
    auto_session_recall_budget_tokens: int = 800
    """Maximum token budget for auto-recalled content injection."""
    auto_session_recall_timeout: float = 3.0
    """Timeout in seconds for the auto session recall search operation.
    Exceeding this silently skips injection without affecting the main flow."""

    @property
    def semantic_collection(self) -> str:
        return f"{self.collection_prefix}_semantic_{_normalize_model_name(self.embedding_model)}"

    @property
    def episodic_collection(self) -> str:
        return f"{self.collection_prefix}_episodic_{_normalize_model_name(self.embedding_model)}"

    @property
    def conversation_collection(self) -> str:
        return f"{self.collection_prefix}_conversation_{_normalize_model_name(self.embedding_model)}"

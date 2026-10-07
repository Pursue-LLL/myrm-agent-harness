"""[POS]: src/myrm_agent_harness/toolkits/memory/batch_learn/models.py
[INPUT]: Raw chunk contents, namespacing attributes, and retry parameters.
[OUTPUT]: Strongly-typed schemas for batch memory learning, namespaced IDs, and chunk resilience.
"""

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ChunkProcessingStatus(StrEnum):
    """Processing state for an individual text chunk."""

    PENDING = "pending"
    SUCCESS = "success"
    RETRIED_SUCCESS = "retried_success"
    FAILED_TRANSIENT = "failed_transient"
    FAILED_PERMANENT = "failed_permanent"


class ItemProvenanceStatus(StrEnum):
    """Lifecycle status for a namespaced learned memory item."""

    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True)
class NamespacedMemoryId:
    """Structured namespaced memory identifier ensuring zero-collision and unambiguous provenance."""

    scope: str
    sub_scope: str
    category: str
    content_fingerprint: str
    full_id: str

    @classmethod
    def create(
        cls,
        scope: str,
        sub_scope: str,
        category: str,
        content_fingerprint: str,
    ) -> "NamespacedMemoryId":
        clean_scope = scope.strip().replace(":", "_")
        clean_sub = sub_scope.strip().replace(":", "_")
        clean_cat = category.strip().replace(":", "_")
        clean_fp = content_fingerprint.strip().replace(":", "_")
        full_id = f"mem:{clean_scope}:{clean_sub}:{clean_cat}:{clean_fp}"
        return cls(
            scope=clean_scope,
            sub_scope=clean_sub,
            category=clean_cat,
            content_fingerprint=clean_fp,
            full_id=full_id,
        )


@dataclass
class BatchRawChunk:
    """Input chunk unit undergoing batch memory extraction."""

    chunk_index: int
    raw_text: str
    source_metadata: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass
class LearnedMemoryItem:
    """Granular canonical memory item extracted from a chunk, bound to a dedicated namespaced ID."""

    namespaced_id: str
    batch_id: str
    chunk_index: int
    content: str
    tags: list[str]
    layer_recommendation: str
    provenance_meta: dict[str, str | int | float | bool]
    status: ItemProvenanceStatus = ItemProvenanceStatus.ACTIVE
    created_at: float = field(default_factory=time.time)


@dataclass
class ChunkExecutionRecord:
    """Diagnostic audit record detailing resilience attempts for an individual chunk."""

    chunk_index: int
    status: ChunkProcessingStatus
    attempt_count: int
    elapsed_ms: float
    error_message: str | None = None
    extracted_items_count: int = 0


@dataclass
class ChunkRetryConfig:
    """Configuration governing exponential backoff and jitter for transient errors."""

    max_retries: int = 3
    initial_delay_sec: float = 0.05
    backoff_factor: float = 2.0
    max_delay_sec: float = 2.0
    enable_jitter: bool = True


@dataclass
class BatchLearnExecutionReport:
    """Comprehensive execution report of a batch memory extraction pipeline."""

    batch_id: str
    total_chunks: int
    successful_chunks: int
    retried_chunks: int
    failed_chunks: int
    total_items_learned: int
    chunk_diagnostics: list[ChunkExecutionRecord]
    items: list[LearnedMemoryItem]
    created_at: float = field(default_factory=time.time)

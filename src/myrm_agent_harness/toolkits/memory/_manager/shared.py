"""Shared imports for MemoryManager mixin modules.

[INPUT]
- memory._internal.governance_service::GovernanceService (POS: governance orchestration for approvals and profile updates)
- memory._internal.maintenance_service::MaintenanceService (POS: maintenance orchestration for health and cycles)
- memory._internal.scope::{derive_namespaces, bind_scope, build_scope, apply_channel_affinity} (POS: namespace derivation and scope helpers)
- memory._internal.search_service::MemorySearchService (POS: search-side orchestration for retrieval)
- memory._internal.storage::{store_*, doc_to_*, count_by_type, ...} (POS: vector/schema storage operations)
- memory._internal.write_service::MemoryWriteService (POS: write-side orchestration for persistence)
- memory.config::MemoryConfig (POS: memory configuration and policy definitions)

[OUTPUT]
- Shared imports, error types, and background-task logging for ``_manager`` mixins

[POS]
Import barrel for MemoryManager mixin modules. Not a public API surface.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.core.hooks import HookRegistryProtocol
from myrm_agent_harness.toolkits.memory._internal.governance_service import (
    GovernanceService,
)
from myrm_agent_harness.toolkits.memory._internal.maintenance import run_forgetting
from myrm_agent_harness.toolkits.memory._internal.maintenance_service import (
    MaintenanceConsolidationResult,
    MaintenanceService,
)
from myrm_agent_harness.toolkits.memory._internal.memory_scanner import (
    MemoryTaintedError,
    scan_and_clean_memory,
)
from myrm_agent_harness.toolkits.memory._internal.scope import (
    MemoryWriteTarget,
    apply_channel_affinity,
    bind_scope,
    build_scope,
    derive_namespaces,
)
from myrm_agent_harness.toolkits.memory._internal.search_service import (
    MemorySearchService,
)
from myrm_agent_harness.toolkits.memory._internal.storage import (
    MemoryError,
    MemoryNotFoundError,
    count_by_type,
    delete_from_vector,
    doc_to_episodic,
    doc_to_semantic,
    get_from_vector,
    list_by_type,
    load_context,
    store_episodic,
    store_episodics_batch,
    store_semantic,
    store_semantics_batch,
    update_vector_memory,
)
from myrm_agent_harness.toolkits.memory._internal.write_service import (
    MemoryWriter,
    build_episodic_deduplicator,
    build_semantic_deduplicator,
)
from myrm_agent_harness.toolkits.memory.archival import ArchivalResult
from myrm_agent_harness.toolkits.memory.backup import (
    BackupMetadata,
    BackupResult,
    MemoryBackupStrategy,
    RestoreResult,
)
from myrm_agent_harness.toolkits.memory.config import (
    AgentMemoryPolicy,
    ConsolidationConfig,
    MemoryConfig,
    RecallMode,
)
from myrm_agent_harness.toolkits.memory.health import (
    HealthScore,
    MaintenanceReport,
    MemorySnapshot,
)
from myrm_agent_harness.toolkits.memory.observability import MemoryRetrievalTrace
from myrm_agent_harness.toolkits.memory.protocols.cache import EmbeddingCacheProtocol
from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
from myrm_agent_harness.toolkits.memory.protocols.graph import GraphStoreProtocol
from myrm_agent_harness.toolkits.memory.protocols.relational import (
    RelationalStoreProtocol,
)
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever
from myrm_agent_harness.toolkits.memory.strategies.preference_stability import (
    CueFamily,
    PreferenceCandidate,
    PreferenceCategory,
    PreferenceStabilityStrategy,
)
from myrm_agent_harness.toolkits.memory.strategies.recurrence import (
    RecurrenceDetector,
)
from myrm_agent_harness.toolkits.memory.types import (
    AnyMemory,
    ConversationMemory,
    EpisodicMemory,
    MemoryMutationRef,
    MemoryMutationResult,
    MemoryScope,
    MemorySearchResult,
    MemoryStatus,
    MemoryType,
    PendingRecord,
    ProceduralMemory,
    ProfileAttributeSnapshot,
    RuleSource,
    SemanticMemory,
)
from myrm_agent_harness.toolkits.vector.base import VectorDocument

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


    ConsolidationLLMFunc = Callable[[str, str], Awaitable[str]]
    FTS5SearcherFunc = Callable[[str, int], Awaitable[list[MemorySearchResult]]]

logger = logging.getLogger(__name__)


def _log_background_task_failure(task: asyncio.Task[object]) -> None:
    if task.cancelled():
        return
    try:
        exc = task.exception()
    except Exception as err:
        logger.warning("Memory manager background task exception lookup failed: %s", err)
        return
    if exc is not None:
        logger.warning("Memory manager background task failed: %s", exc)


__all__ = [
    "TYPE_CHECKING",
    "UTC",
    "AgentMemoryPolicy",
    "AnyMemory",
    "ArchivalResult",
    "BackupMetadata",
    "BackupResult",
    "BaseChatModel",
    "ConsolidationConfig",
    "ConversationMemory",
    "CueFamily",
    "EmbeddingCacheProtocol",
    "EmbeddingProtocol",
    "EpisodicMemory",
    "GovernanceService",
    "GraphStoreProtocol",
    "HealthScore",
    "HookRegistryProtocol",
    "MaintenanceConsolidationResult",
    "MaintenanceReport",
    "MaintenanceService",
    "MemoryBackupStrategy",
    "MemoryConfig",
    "MemoryError",
    "MemoryMutationRef",
    "MemoryMutationResult",
    "MemoryNotFoundError",
    "MemoryRetrievalTrace",
    "MemoryRetriever",
    "MemoryScope",
    "MemorySearchResult",
    "MemorySearchService",
    "MemorySnapshot",
    "MemoryStatus",
    "MemoryTaintedError",
    "MemoryType",
    "MemoryWriteTarget",
    "MemoryWriter",
    "PendingRecord",
    "PreferenceCandidate",
    "PreferenceCategory",
    "PreferenceStabilityStrategy",
    "ProceduralMemory",
    "ProfileAttributeSnapshot",
    "RecallMode",
    "RecurrenceDetector",
    "RelationalStoreProtocol",
    "RestoreResult",
    "RuleSource",
    "SemanticMemory",
    "Sequence",
    "VectorDocument",
    "VectorStoreProtocol",
    "_log_background_task_failure",
    "annotations",
    "apply_channel_affinity",
    "bind_scope",
    "build_episodic_deduplicator",
    "build_scope",
    "build_semantic_deduplicator",
    "count_by_type",
    "datetime",
    "delete_from_vector",
    "derive_namespaces",
    "doc_to_episodic",
    "doc_to_semantic",
    "get_from_vector",
    "list_by_type",
    "load_context",
    "logger",
    "run_forgetting",
    "scan_and_clean_memory",
    "store_episodic",
    "store_episodics_batch",
    "store_semantic",
    "store_semantics_batch",
    "suppress",
    "timedelta",
    "update_vector_memory",
]

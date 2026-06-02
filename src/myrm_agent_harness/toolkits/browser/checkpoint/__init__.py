"""Browser task checkpoint and recovery system.

Provides task-level checkpoint/resume capabilities for browser automation:
- IncrementalSessionCheckpointer: Decorator for LangGraph checkpointer with incremental Session Vault saving
- CheckpointMetadata: Extended metadata structure (current_url, session_domain, counters)
- AutoRecoveryOrchestrator: Automatic recovery of incomplete tasks on startup
- ParallelRecoveryOrchestrator: Parallel recovery with browser session pre-warming
- CheckpointMetrics: Monitoring and observability for checkpoint operations


[INPUT]
- langgraph.checkpoint.base::BaseCheckpointSaver (POS: LangGraph checkpointer base class)
- session_vault::SessionVault (POS: AES-256-GCM encrypted session storage)
- observability::BrowserObservability (POS: browser observability manager)

[OUTPUT]
- IncrementalSessionCheckpointer: checkpointer decorator with incremental Session Vault saving
- CheckpointMetadata: extended metadata structure
- AutoRecoveryOrchestrator: startup auto-recovery
- ParallelRecoveryOrchestrator: parallel recovery + pre-warming
- CheckpointMetrics: monitoring metrics

[POS]
Task-level checkpoint/resume module for the browser toolkit. Fully reuses LangGraph Checkpointer's persistence capabilities,
only saves incrementally when Session Vault state changes, supports automatic recovery of incomplete tasks on startup with parallel pre-warming.
"""

from .context_integration import BrowserCheckpointHelper, create_browser_context_updater
from .default_checkpointer import create_default_checkpointer, create_memory_checkpointer
from .hash_cache import LRUHashCache
from .incremental_checkpointer import IncrementalSessionCheckpointer
from .metadata import CheckpointMetadata, SerializedMessage, extract_metadata_from_messages, merge_metadata
from .metrics import CheckpointMetrics
from .orchestrator import AutoRecoveryOrchestrator, ParallelRecoveryOrchestrator, RecoveryContext, RecoverySummary
from .protocols import ThreadStoreProtocol
from .session_state import (
    BrowserState,
    PlaywrightStorageState,
    apply_storage_state,
    get_browser_state,
    restore_browser_state,
)
from .thread_models import ThreadRecord, ThreadStatus
from .thread_registry import ThreadStore, create_thread_tables

__all__ = [
    "AutoRecoveryOrchestrator",
    "BrowserCheckpointHelper",
    "BrowserState",
    "CheckpointMetadata",
    "CheckpointMetrics",
    "IncrementalSessionCheckpointer",
    "LRUHashCache",
    "ParallelRecoveryOrchestrator",
    "PlaywrightStorageState",
    "RecoveryContext",
    "RecoverySummary",
    "SerializedMessage",
    "ThreadRecord",
    "ThreadStatus",
    "ThreadStore",
    "ThreadStoreProtocol",
    "apply_storage_state",
    "create_browser_context_updater",
    "create_default_checkpointer",
    "create_memory_checkpointer",
    "create_thread_tables",
    "extract_metadata_from_messages",
    "get_browser_state",
    "merge_metadata",
    "restore_browser_state",
]

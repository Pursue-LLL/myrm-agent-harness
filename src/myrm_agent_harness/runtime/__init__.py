"""Agent runtime infrastructure for single-instance execution.

Provides resource management, context lifecycle, storage quota, and monitoring
for a single Agent instance. Follows the framework's three core responsibilities:
resource management, performance optimization, and self-protection.

Subpackages:
- context/: Context lifecycle — cleanup, config, metrics, tracking, reading, offload
- quota/: Storage quota management and monitoring

Core modules:
- resource_monitor: Resource usage monitoring
- memory_pressure: Global memory pressure detection and subscriber notification
- execution_paths: Path constants, utilities, and access tracking
- compression: File compression utilities
- doctor: Global diagnostics and health checks
- artifact_judge: Artifact classification
- checkpoint_protocol: Checkpointer protocol definition
- fork_types: Conversation fork data structures
"""

from myrm_agent_harness.runtime.context import (
    ContextCleanupConfig,
    ContextCleanupScheduler,
    ContextMetrics,
    FileAccessTracker,
    StorageQuotaConfig,
    TransparentFileReader,
    cleanup_context_files_async,
    cleanup_context_files_local,
    cleanup_orphan_context_files,
    cleanup_orphan_context_files_async,
    cleanup_session_context_files,
    create_compress_offload_callback,
    get_context_metrics,
    get_file_access_tracker,
    read_context_file_async,
    read_context_file_sync,
    set_context_metrics,
)
from myrm_agent_harness.runtime.events import BaseEvent, EventBus, IdleTaskProgressEvent, get_event_bus
from myrm_agent_harness.runtime.execution_paths import (
    ARTIFACTS_ROOT,
    CONTEXT_ROOT,
    MEMORIES_ROOT,
    PERSISTENT_ROOT,
    ensure_context_dir_exists,
    get_compacted_output_path,
    get_context_session_dir,
    get_workspace_relative_path,
)
from myrm_agent_harness.runtime.fork_types import ForkInfo
from myrm_agent_harness.runtime.maintenance import (
    AgentHealthScore,
    CapacityDenial,
    CapacityTicket,
    DeviceLoadSensor,
    GlobalAdaptiveScheduler,
    MaintenanceTaskType,
    SaaSLoadSensor,
    SystemLoadLevel,
    SystemLoadSnapshot,
    compute_health_score,
    get_maintenance_scheduler,
    init_maintenance_scheduler,
)
from myrm_agent_harness.runtime.memory_pressure import (
    MemoryPressureMonitor,
    PressureConfig,
    PressureEvent,
    PressureLevel,
    PressureSubscriber,
    get_memory_pressure_monitor,
    init_memory_pressure_monitor,
)
from myrm_agent_harness.runtime.quota import (
    QuotaExceededError,
    SimpleStorageQuotaManager,
    StorageQuotaChecker,
)
from myrm_agent_harness.runtime.resource_monitor import ResourceMonitor

__all__ = [
    "ARTIFACTS_ROOT",
    "CONTEXT_ROOT",
    "MEMORIES_ROOT",
    "PERSISTENT_ROOT",
    "AgentHealthScore",
    "BaseEvent",
    "CapacityDenial",
    "CapacityTicket",
    "ContextCleanupConfig",
    "ContextCleanupScheduler",
    "ContextMetrics",
    "DeviceLoadSensor",
    "EventBus",
    "FileAccessTracker",
    "ForkInfo",
    "GlobalAdaptiveScheduler",
    "IdleTaskProgressEvent",
    "MaintenanceTaskType",
    "MemoryPressureMonitor",
    "PressureConfig",
    "PressureEvent",
    "PressureLevel",
    "PressureSubscriber",
    "QuotaExceededError",
    "ResourceMonitor",
    "SaaSLoadSensor",
    "SimpleStorageQuotaManager",
    "StorageQuotaChecker",
    "StorageQuotaConfig",
    "SystemLoadLevel",
    "SystemLoadSnapshot",
    "TransparentFileReader",
    "cleanup_context_files_async",
    "cleanup_context_files_local",
    "cleanup_orphan_context_files",
    "cleanup_orphan_context_files_async",
    "cleanup_session_context_files",
    "compute_health_score",
    "create_compress_offload_callback",
    "ensure_context_dir_exists",
    "get_compacted_output_path",
    "get_context_metrics",
    "get_context_session_dir",
    "get_event_bus",
    "get_file_access_tracker",
    "get_maintenance_scheduler",
    "get_memory_pressure_monitor",
    "get_workspace_relative_path",
    "init_maintenance_scheduler",
    "init_memory_pressure_monitor",
    "read_context_file_async",
    "read_context_file_sync",
    "set_context_metrics",
]

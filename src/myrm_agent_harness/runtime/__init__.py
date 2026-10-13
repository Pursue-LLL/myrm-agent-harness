"""Agent runtime infrastructure for single-instance execution.

Provides resource management, context lifecycle, storage quota, and monitoring
for a single Agent instance. Follows the framework's three core responsibilities:
resource management, performance optimization, and self-protection.

Subpackages:
- context/: Context lifecycle — cleanup, config, metrics, tracking, reading, offload
- checkpointing/: Checkpointer factory
- events/: Runtime event bus
- cognitive_clock/: Cooperative pause signals for background work
- maintenance/: Global adaptive maintenance scheduling
- quota/: Storage quota management
- install_guard/: Dual-wheel install readiness
- diagnostics/: Doctor and compliance self-audit
- survival/: Memory pressure, resource monitor, startup timing
- paths/: Execution path constants and compression
- artifacts/: Checkpointer protocol
- deps/: Lazy optional dependency install
"""

from myrm_agent_harness.runtime.cognitive_clock import (
    CooperativePauseSignal,
    PauseRequestedError,
    get_global_pause_signal,
)
from myrm_agent_harness.runtime.context import (
    ContextCleanupScheduler,
    ContextMetrics,
    FileAccessTracker,
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
from myrm_agent_harness.runtime.deps import lazy_deps
from myrm_agent_harness.runtime.events import BaseEvent, EventBus, IdleTaskProgressEvent, get_event_bus
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
    get_maintenance_scheduler,
    init_maintenance_scheduler,
)
from myrm_agent_harness.runtime.paths.execution_paths import (
    ARTIFACTS_ROOT,
    CONTEXT_ROOT,
    MEMORIES_ROOT,
    PERSISTENT_ROOT,
    ensure_context_dir_exists,
    get_compacted_output_path,
    get_context_session_dir,
    get_workspace_relative_path,
)
from myrm_agent_harness.runtime.quota import (
    QuotaExceededError,
    SimpleStorageQuotaManager,
    StorageQuotaChecker,
)
from myrm_agent_harness.runtime.survival.memory_pressure import (
    MemoryPressureMonitor,
    PressureConfig,
    PressureEvent,
    PressureLevel,
    PressureSubscriber,
    get_memory_pressure_monitor,
    init_memory_pressure_monitor,
)
from myrm_agent_harness.runtime.survival.resource_monitor import ResourceMonitor

__all__ = [
    "ARTIFACTS_ROOT",
    "CONTEXT_ROOT",
    "MEMORIES_ROOT",
    "PERSISTENT_ROOT",
    "AgentHealthScore",
    "BaseEvent",
    "CapacityDenial",
    "CapacityTicket",
    "CooperativePauseSignal",
    "ContextCleanupScheduler",
    "ContextMetrics",
    "DeviceLoadSensor",
    "EventBus",
    "FileAccessTracker",
    "GlobalAdaptiveScheduler",
    "IdleTaskProgressEvent",
    "lazy_deps",
    "MaintenanceTaskType",
    "MemoryPressureMonitor",
    "PressureConfig",
    "PressureEvent",
    "PressureLevel",
    "PressureSubscriber",
    "QuotaExceededError",
    "PauseRequestedError",
    "ResourceMonitor",
    "SaaSLoadSensor",
    "SimpleStorageQuotaManager",
    "StorageQuotaChecker",
    "SystemLoadLevel",
    "SystemLoadSnapshot",
    "TransparentFileReader",
    "cleanup_context_files_async",
    "cleanup_context_files_local",
    "cleanup_orphan_context_files",
    "cleanup_orphan_context_files_async",
    "cleanup_session_context_files",
    "create_compress_offload_callback",
    "ensure_context_dir_exists",
    "get_compacted_output_path",
    "get_context_metrics",
    "get_context_session_dir",
    "get_event_bus",
    "get_file_access_tracker",
    "get_global_pause_signal",
    "get_maintenance_scheduler",
    "get_memory_pressure_monitor",
    "get_workspace_relative_path",
    "init_maintenance_scheduler",
    "init_memory_pressure_monitor",
    "read_context_file_async",
    "read_context_file_sync",
    "set_context_metrics",
]

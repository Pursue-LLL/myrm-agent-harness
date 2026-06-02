"""Global Adaptive Maintenance Scheduling.

Provides system-load-aware throttling for background maintenance tasks
(evolution, context compaction, storage cleanup). Prevents maintenance
from degrading user-facing performance.

Key components:
- LoadSensor protocol + implementations (Device / SaaS)
- GlobalAdaptiveScheduler — ticket-based capacity control
- AgentHealthScore — composite health metric
- CapacityTicket — permission token for maintenance tasks
"""

from .health import compute_health_score
from .protocols import (
    AgentHealthScore,
    CapacityDenial,
    CapacityTicket,
    LoadSensor,
    MaintenanceScheduler,
    MaintenanceTaskType,
    SystemLoadLevel,
    SystemLoadSnapshot,
)
from .scheduler import (
    GlobalAdaptiveScheduler,
    get_maintenance_scheduler,
    init_maintenance_scheduler,
)
from .sensors import DeviceLoadSensor, SaaSLoadSensor

__all__ = [
    "AgentHealthScore",
    "CapacityDenial",
    "CapacityTicket",
    "DeviceLoadSensor",
    "GlobalAdaptiveScheduler",
    "LoadSensor",
    "MaintenanceScheduler",
    "MaintenanceTaskType",
    "SaaSLoadSensor",
    "SystemLoadLevel",
    "SystemLoadSnapshot",
    "compute_health_score",
    "get_maintenance_scheduler",
    "init_maintenance_scheduler",
]

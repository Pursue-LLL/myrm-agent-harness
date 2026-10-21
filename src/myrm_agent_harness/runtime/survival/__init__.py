"""Runtime survival — memory pressure, resource monitor, startup timing, and desktop watchdog suite.

[OUTPUT]
- PressureLevel, MemoryPressureMonitor, init_memory_pressure_monitor, get_memory_pressure_monitor
- DehydrationState, MemoryAlertLevel, SessionTurn, DehydratedSessionTurn, MemoryCompactionReceipt, ArchiveVolume
- SessionContextDehydrator
- DesktopMemoryWatchdog, get_current_rss_bytes
- LongSessionRollingArchiver

[INPUT]
- (none — 标准库与内建依赖)

[OUTPUT]
- (模块级副作用与注册)

[POS]
Runtime survival — memory pressure, resource monitor, startup timing, and desktop watchdog suite.
"""

from myrm_agent_harness.runtime.survival.desktop_memory_watchdog import (
    DesktopMemoryWatchdog,
    get_current_rss_bytes,
)
from myrm_agent_harness.runtime.survival.desktop_watchdog_types import (
    ArchiveVolume,
    DehydratedSessionTurn,
    DehydrationState,
    MemoryAlertLevel,
    MemoryCompactionReceipt,
    SessionTurn,
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
from myrm_agent_harness.runtime.survival.rolling_archive import (
    LongSessionRollingArchiver,
)
from myrm_agent_harness.runtime.survival.session_dehydration import (
    SessionContextDehydrator,
)

__all__ = [
    "ArchiveVolume",
    "DehydratedSessionTurn",
    "DehydrationState",
    "DesktopMemoryWatchdog",
    "LongSessionRollingArchiver",
    "MemoryAlertLevel",
    "MemoryCompactionReceipt",
    "MemoryPressureMonitor",
    "PressureConfig",
    "PressureEvent",
    "PressureLevel",
    "PressureSubscriber",
    "SessionContextDehydrator",
    "SessionTurn",
    "get_current_rss_bytes",
    "get_memory_pressure_monitor",
    "init_memory_pressure_monitor",
]

"""Native Subagent Fine-Grained Lifecycle Toolchain Pack.

Provides thread-safe atomic primitives: spawn, wait, list, send_input, kill.

[INPUT]
- lifecycle_manager
- types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Native Subagent Fine-Grained Lifecycle Toolchain Pack.
"""

from .lifecycle_manager import SubagentLifecycleManager
from .types import (
    SubagentEventItem,
    SubagentInputMessage,
    SubagentLifecycleError,
    SubagentNotFoundError,
    SubagentSpawnRequest,
    SubagentStatusEnum,
    SubagentTaskRecord,
    SubagentTimeoutError,
    SubagentWaitResult,
)

__all__ = [
    "SubagentEventItem",
    "SubagentInputMessage",
    "SubagentLifecycleError",
    "SubagentLifecycleManager",
    "SubagentNotFoundError",
    "SubagentSpawnRequest",
    "SubagentStatusEnum",
    "SubagentTaskRecord",
    "SubagentTimeoutError",
    "SubagentWaitResult",
]

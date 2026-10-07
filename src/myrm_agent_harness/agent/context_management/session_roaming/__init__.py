"""跨设备会话实时漫游、团队协作接力与沙箱热镜像套件模块。

[INPUT]
- session_roaming_types.py: 契约模型
- session_roaming_engine.py: 核心引擎实现

[OUTPUT]
- 导出 CollaborationRole, DevicePlatform, SessionRoamingBreakpoint, SandboxWarmMirrorSpec, ExecutableTeamShareBundle, ForkAndContinueResult, DeviceAgnosticSessionRoamingEngine

[POS]
- 位于 context_management/session_roaming/__init__.py
"""

from .session_roaming_engine import DeviceAgnosticSessionRoamingEngine
from .session_roaming_types import (
    CollaborationRole,
    DevicePlatform,
    ExecutableTeamShareBundle,
    ForkAndContinueResult,
    SandboxWarmMirrorSpec,
    SessionRoamingBreakpoint,
)

__all__ = [
    "CollaborationRole",
    "DeviceAgnosticSessionRoamingEngine",
    "DevicePlatform",
    "ExecutableTeamShareBundle",
    "ForkAndContinueResult",
    "SandboxWarmMirrorSpec",
    "SessionRoamingBreakpoint",
]

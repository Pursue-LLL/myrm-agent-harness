"""Cross-Surface Agent Activity Conversation Bridge package.

Ingresses external agent activities from Tauri sidecar, CLI sessions, and cron tasks
into Fleet Canvas with bounded recent projection and read-only presence.

[INPUT]
- ingress_bridge
- types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Cross-Surface Agent Activity Conversation Bridge package.
"""

from .ingress_bridge import CrossSurfaceActivityBridge
from .types import (
    ActivityKind,
    CrossSurfaceProjectionSnapshot,
    IngressActivityItem,
    PresenceStatus,
    SurfaceOrigin,
    SurfacePresenceSummary,
)

__all__ = [
    "ActivityKind",
    "CrossSurfaceActivityBridge",
    "CrossSurfaceProjectionSnapshot",
    "IngressActivityItem",
    "PresenceStatus",
    "SurfaceOrigin",
    "SurfacePresenceSummary",
]

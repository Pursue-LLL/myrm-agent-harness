"""VNC visual desktop streaming for sandbox environments.

Provides real-time screen sharing via x11vnc + websockify, enabling users to
observe and take over Agent browser operations through noVNC in the frontend.
"""

from myrm_agent_harness.toolkits.vnc.server import VncServer, get_environment_hint
from myrm_agent_harness.toolkits.vnc.takeover import (
    TakeoverCoordinator,
    TakeoverLifecycleHook,
    TakeoverState,
)

__all__ = ["VncServer", "TakeoverCoordinator", "TakeoverLifecycleHook", "TakeoverState", "get_environment_hint"]

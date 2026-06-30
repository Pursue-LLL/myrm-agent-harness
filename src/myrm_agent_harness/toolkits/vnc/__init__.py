"""VNC visual desktop streaming for sandbox environments.

[INPUT]
- toolkits.vnc.server::VncServer (POS: VNC server lifecycle manager for x11vnc + websockify on existing Xvfb.)
- toolkits.vnc.server::get_environment_hint (POS: Detect VNC/Xvfb availability for system prompt injection.)
- toolkits.vnc.takeover::TakeoverCoordinator (POS: Human-agent browser control handoff state machine.)
- toolkits.vnc.takeover::TakeoverLifecycleHook (POS: Optional async callbacks for takeover start/end.)
- toolkits.vnc.takeover::TakeoverState (POS: Takeover state enum for AGENT_ACTIVE vs USER_TAKEOVER.)

[OUTPUT]
- VncServer: lazy-start VNC stack on existing Xvfb display
- get_environment_hint: prompt line for VNC availability
- TakeoverCoordinator: human takeover coordination
- TakeoverLifecycleHook: optional lifecycle callbacks
- TakeoverState: takeover state enum

[POS]
VNC toolkit package entry. Re-exports server lifecycle and human takeover APIs for sandbox visual desktop streaming.
"""

from myrm_agent_harness.toolkits.vnc.server import VncServer, get_environment_hint
from myrm_agent_harness.toolkits.vnc.takeover import (
    TakeoverCoordinator,
    TakeoverLifecycleHook,
    TakeoverState,
)

__all__ = ["VncServer", "TakeoverCoordinator", "TakeoverLifecycleHook", "TakeoverState", "get_environment_hint"]

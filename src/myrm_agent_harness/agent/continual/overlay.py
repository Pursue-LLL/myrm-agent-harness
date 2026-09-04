"""Continual overlay facade bridging to canonical session_overlay subsystem.

[POS]
Re-exports session_overlay definitions to maintain backward compatibility
for existing callers in middlewares and lifecycle hooks.
"""

from myrm_agent_harness.agent.session_overlay.manager import (
    SessionOverlayManager,
    get_session_overlay_manager,
    reset_session_overlay_manager,
)
from myrm_agent_harness.agent.session_overlay.schema import (
    DEFAULT_OVERLAY_TTL,
    DEFAULT_OVERLAY_TTL_TURNS,
    OverlayScope,
    OverlayStatus,
    OverlayTargetType,
    SessionOverlay,
    SessionOverlaySnapshot,
)
from myrm_agent_harness.agent.session_overlay.synthesizer import (
    synthesize_fault_site_overlay,
    synthesize_loop_stall_overlay,
)

OverlayShellType = OverlayTargetType

__all__ = [
    "DEFAULT_OVERLAY_TTL",
    "DEFAULT_OVERLAY_TTL_TURNS",
    "OverlayScope",
    "OverlayShellType",
    "OverlayStatus",
    "OverlayTargetType",
    "SessionOverlay",
    "SessionOverlayManager",
    "SessionOverlaySnapshot",
    "get_session_overlay_manager",
    "reset_session_overlay_manager",
    "synthesize_fault_site_overlay",
    "synthesize_loop_stall_overlay",
]

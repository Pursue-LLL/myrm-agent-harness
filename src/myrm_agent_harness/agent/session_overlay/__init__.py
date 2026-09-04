"""Continual fault-site session overlay subsystem for zero-reset agent self-healing.

[POS]
Provides session-level runtime modifications (prompt patches, temporary skill
variants, subagent config overlays, procedural memory negative constraints)
triggered at fault sites without resetting checkpoints or losing agent context.
"""

from myrm_agent_harness.agent.session_overlay.manager import (
    MAX_ACTIVE_OVERLAYS,
    SessionOverlayManager,
    get_session_overlay_manager,
    reset_session_overlay_manager,
)
from myrm_agent_harness.agent.session_overlay.schema import (
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

__all__ = [
    "MAX_ACTIVE_OVERLAYS",
    "OverlayScope",
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

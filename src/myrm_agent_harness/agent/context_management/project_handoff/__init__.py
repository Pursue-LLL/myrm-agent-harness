"""Ten-Second Cross-Session Project Handoff Protocol Suite (Item 218).

[INPUT]
- project_handoff_types: Strongly typed contracts and configurations.
- project_handoff_engine: TenSecondProjectHandoffEngine implementation.

[OUTPUT]
- Public exports of Project Handoff Suite.

[POS]
- Provides zero-context re-prompting intent probes, avatar file sniffing,
- and instant 10-second alignment handshakes across new sessions and model switches.
"""

from .project_handoff_engine import TenSecondProjectHandoffEngine
from .project_handoff_types import (
    HandoffHandshakeResponse,
    ProjectHandoffConfig,
    ProjectHandoffStatus,
    ProjectWorkspaceDossier,
)

__all__ = [
    "HandoffHandshakeResponse",
    "ProjectHandoffConfig",
    "ProjectHandoffStatus",
    "ProjectWorkspaceDossier",
    "TenSecondProjectHandoffEngine",
]

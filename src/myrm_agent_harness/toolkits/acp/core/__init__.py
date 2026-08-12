"""Shared runtime infrastructure for the ACP toolkit.

Hosts cross-cutting mechanisms used by the runtime and server subsystems:
- ``backend_detector``: CLI agent backend auto-detection.
- ``event_bus``: publish-subscribe event bus for the runtime system.
- ``health_monitor``: backend liveness monitoring with backoff and restart budget.
- ``permission``: framework-level permission manager (safe / ask / allow_all / bypass).

Modules here are consumed via explicit submodule imports (e.g.
``from myrm_agent_harness.toolkits.acp.core.event_bus import EventBus``);
no public symbols are re-exported at this package level.

[POS]
Shared cross-cutting runtime infrastructure for the ACP toolkit (no re-exports).
"""

from __future__ import annotations

__all__: list[str] = []

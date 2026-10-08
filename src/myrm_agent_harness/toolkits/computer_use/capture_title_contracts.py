"""Cross-process window title contracts for capture exclusion (host ↔ harness).

[INPUT]
- None (constants only)

[OUTPUT]
- SNAPSHOT_ONLY_EXCLUDED_CAPTURE_TITLES: titles merged into full-screen capture only

[POS]
Keeps harness-side snapshot exclusion aligned with Tauri window titles without pulling
server/desktop imports. Pointer guard must NOT include click-through overlays listed here.
"""

from __future__ import annotations

# Must match myrm-agent-desktop visual_approval_overlay.rs WebviewWindowBuilder::title.
SNAPSHOT_ONLY_EXCLUDED_CAPTURE_TITLES: frozenset[str] = frozenset({"Visual Approval Overlay"})

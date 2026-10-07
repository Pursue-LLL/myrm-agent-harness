"""Zero-LLM emergency snapshot generator for graceful unload and crash fallback.

Synthesizes structured handoff memorandums in sub-millisecond execution
without waiting for LLM API roundtrips.
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.unload_guard.types::EmergencyFlushRequest (POS: Type definitions for desktop/WebUI unload
  and graceful flush finalize guard.)

[OUTPUT]
- ZeroLlmEmergencySnapshotBuilder: Pure heuristic template builder creating emergency handoff markdown.

[POS]
Zero-LLM emergency snapshot generator for graceful unload and crash fallback.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.unload_guard.types import EmergencyFlushRequest


class ZeroLlmEmergencySnapshotBuilder:
    """Pure heuristic template builder creating emergency handoff markdown."""

    def build_markdown(self, request: EmergencyFlushRequest, handoff_id: str) -> str:
        """Format an emergency flush request into standard human-readable markdown."""
        lines: list[str] = [
            f"# Emergency Handoff Memorandum [{handoff_id}]",
            f"- **Session ID:** {request.session_id}",
            f"- **Trigger Reason:** {request.reason.value}",
            f"- **Active Goal:** {request.active_goal}",
        ]

        if request.last_tool_call:
            lines.append(f"- **Last Tool Call:** `{request.last_tool_call}`")

        # 0. Unsaved notes section
        if request.unsaved_notes:
            lines.extend(["", "### Unsaved Notes / Scratchpad"])
            for note in request.unsaved_notes:
                lines.append(f"- {note}")

        # 1. Modified files section
        if request.modified_files:
            lines.extend(["", "### Files Modified in Flight"])
            for f in request.modified_files:
                lines.append(f"- `{f}`")

        # 2. Encountered errors section
        if request.recent_errors:
            lines.extend(["", "### Recent Unresolved Errors / Blockers"])
            for err in request.recent_errors:
                lines.append(f"- ⚠️ {err}")

        # 3. Next action items section
        lines.extend(["", "### Immediate Next Actions for Recovery"])
        if request.next_actions:
            for idx, act in enumerate(request.next_actions):
                lines.append(f"{idx+1}. {act}")
        else:
            lines.append("1. Inspect current modified files and verify execution state.")

        lines.extend([
            "",
            "> *Note: This snapshot was automatically assembled via Zero-LLM Crash-Proof Fallback upon unload/close.*",
        ])

        return "\n".join(lines)

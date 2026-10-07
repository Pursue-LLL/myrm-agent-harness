"""Read-only context snapshot capturer for non-intrusive peer agent inspection.

Captures sanitized transcript summaries and workspace references from peer sessions
with zero side effects: the target agent is neither alerted nor interrupted, and
the referencing agent receives strict read-only boundary constraints.

[INPUT]
- runtime.context.agent_mention_types::ReadOnlySnapshotBundle (POS: Agent mention dual-mode interaction
  types and communication contracts.)
- runtime.context.project_hierarchy_session_types::ArchivedMessageEntry (POS: Project hierarchy session
  archive and keyword resurrection types.)

[OUTPUT]
- ReadOnlySnapshotCapturer: Safely extracts read-only context snapshots from target sessions.

[POS]
Read-only context snapshot capturer for non-intrusive peer agent inspection.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from .agent_mention_types import ReadOnlySnapshotBundle
from .project_hierarchy_session_types import ArchivedMessageEntry


class ReadOnlySnapshotCapturer:
    """Safely extracts read-only context snapshots from target sessions."""

    def capture_snapshot(
        self,
        source_session_id: str,
        target_session_id: str,
        messages: Sequence[ArchivedMessageEntry],
        workspace_path: str = "",
        max_chars: int = 4000,
    ) -> ReadOnlySnapshotBundle:
        """Constructs an immutable snapshot bundle from a sequence of message turns."""
        now = time.time()
        if not messages:
            return ReadOnlySnapshotBundle(
                source_session_id=source_session_id,
                target_session_id=target_session_id,
                summary_markdown="*(No conversation history available for this peer session)*",
                retained_messages_count=0,
                captured_at=now,
                workspace_path=workspace_path,
            )

        summary_parts: list[str] = []
        char_count = 0

        # Extract recent turns up to max_chars budget
        for msg in reversed(messages):
            role_header = f"[{msg.role.upper()}]: "
            content_preview = msg.content.strip().replace("\n", " ")
            if len(content_preview) > 300:
                content_preview = content_preview[:300] + "..."

            line = f"{role_header}{content_preview}"
            if msg.error_traces:
                line += f" (Error: {'; '.join(msg.error_traces)})"
            if msg.file_references:
                line += f" (Files: {', '.join(msg.file_references)})"

            line_len = len(line)
            if char_count + line_len > max_chars:
                summary_parts.append("... [earlier history truncated for brevity] ...")
                break

            summary_parts.append(line)
            char_count += line_len

        summary_parts.reverse()
        summary_md = "\n".join(summary_parts)

        return ReadOnlySnapshotBundle(
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            summary_markdown=summary_md,
            retained_messages_count=len(messages),
            captured_at=now,
            workspace_path=workspace_path,
        )

    def format_mention_prompt_block(self, snapshot: ReadOnlySnapshotBundle) -> str:
        """Renders an unambiguous read-only prompt block for LLM inference."""
        lines = [
            "<agent_reference mode='read_only'>",
            f"Peer Session Reference: {snapshot.target_session_id}",
            "NOTICE: This is an immutable read-only context snapshot. The peer agent is unaware of this inquiry.",
            "You CANNOT modify the peer agent's workspace or send messages to it.",
        ]
        if snapshot.workspace_path:
            lines.append(f"Workspace Reference: {snapshot.workspace_path}")

        lines.extend([
            "--- Snapshot Transcript ---",
            snapshot.summary_markdown,
            "---------------------------",
            "</agent_reference>",
        ])
        return "\n".join(lines)

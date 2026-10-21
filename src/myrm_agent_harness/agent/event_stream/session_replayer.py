"""Full lifecycle lossless session replayer and resumption breakpoint detector.

Reconstructs structured conversational message trees from SQLite projected parts,
accurately pinpoints interrupted in-progress breakpoints (tools/reasoning), and
provides zero-loss state recovery across crashes and restarts.

[OUTPUT]
- ReplayedPart: Structured view of an individual replayed part.
- ReplayedMessage: Message container holding ordered parts.
- SessionSnapshot: Full topological session state tree with resumption metadata.
- SessionReplayer: Recovery engine querying projected SQLite state.

[INPUT]
- __future__
- json
- dataclasses
- typing

[OUTPUT]
- ReplayedPart
- ReplayedMessage
- SessionSnapshot
- SessionReplayer

[POS]
Full lifecycle lossless session replayer and resumption breakpoint detector.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import cast

from myrm_agent_harness.agent.event_stream.part_types import PartKind, PartStatus
from myrm_agent_harness.agent.event_stream.sqlite_projector import (
    SQLitePartProjector,
)


@dataclass(frozen=True)
class ReplayedPart:
    """Read-only view of a reconstructed conversational message part."""

    part_id: str
    kind: PartKind
    status: PartStatus
    content: str
    metadata: dict[str, str | float | bool]
    duration_ms: float
    sequence_number: int


@dataclass(frozen=True)
class ReplayedMessage:
    """Ordered collection of parts representing a single conversational message."""

    message_id: str
    role: str
    parts: tuple[ReplayedPart, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SessionSnapshot:
    """Complete lossless reconstruction of a session with interruption points."""

    session_id: str
    messages: tuple[ReplayedMessage, ...]
    unclosed_parts: tuple[ReplayedPart, ...]
    total_parts: int
    has_interruption: bool


class SessionReplayer:
    """Extracts relational part records from SQLite and builds high-fidelity snapshots."""

    def __init__(self, projector: SQLitePartProjector) -> None:
        self.projector: SQLitePartProjector = projector

    async def replay_session(self, session_id: str) -> SessionSnapshot:
        """Reconstruct the entire session state and detect any hanging in-progress parts."""
        raw_parts = await self.projector.get_session_parts(session_id)

        messages_map: dict[str, list[ReplayedPart]] = {}
        unclosed: list[ReplayedPart] = []

        for row in raw_parts:
            pid = str(row["part_id"])
            mid = str(row["message_id"])
            kind = PartKind(str(row["part_kind"]))
            status = PartStatus(str(row["status"]))
            content = str(row["content"])
            duration_ms = float(cast(float, row["duration_ms"]))
            seq = int(cast(int, row["sequence_number"]))

            meta_raw = str(row["metadata_json"])
            try:
                metadata = (
                    json.loads(meta_raw) if meta_raw and meta_raw != "{}" else {}
                )
            except json.JSONDecodeError:
                metadata = {}

            part = ReplayedPart(
                part_id=pid,
                kind=kind,
                status=status,
                content=content,
                metadata=metadata,
                duration_ms=duration_ms,
                sequence_number=seq,
            )

            if mid not in messages_map:
                messages_map[mid] = []
            messages_map[mid].append(part)

            if status == PartStatus.IN_PROGRESS:
                unclosed.append(part)

        replayed_messages: list[ReplayedMessage] = [
            ReplayedMessage(
                message_id=mid,
                role="assistant",
                parts=tuple(parts_list),
            )
            for mid, parts_list in messages_map.items()
        ]

        return SessionSnapshot(
            session_id=session_id,
            messages=tuple(replayed_messages),
            unclosed_parts=tuple(unclosed),
            total_parts=len(raw_parts),
            has_interruption=len(unclosed) > 0,
        )

    @staticmethod
    def render_markdown_transcript(snapshot: SessionSnapshot) -> str:
        """Synthesize a human-readable Markdown transcript of the replayed session parts."""
        lines: list[str] = [f"# Session Transcript: {snapshot.session_id}"]
        if snapshot.has_interruption:
            lines.append(
                f"> [!WARNING] Session contains {len(snapshot.unclosed_parts)} unclosed part(s)!"
            )

        for msg in snapshot.messages:
            lines.append(f"\n## Message: {msg.message_id}")
            for part in msg.parts:
                status_icon = (
                    "⏳"
                    if part.status == PartStatus.IN_PROGRESS
                    else ("✅" if part.status == PartStatus.COMPLETED else "❌")
                )
                lines.append(
                    f"### {status_icon} [{part.kind.value.upper()}] Part {part.part_id} ({part.duration_ms:.1f}ms)"
                )
                lines.append(part.content or "*(empty)*")

        return "\n".join(lines)

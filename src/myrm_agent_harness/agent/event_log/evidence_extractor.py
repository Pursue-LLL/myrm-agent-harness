"""Session Evidence Extractor for Trace Learning.

[INPUT]
- agent.event_log.protocol::EventLogBackend (POS: Protocol contract. Framework provides FileEventLogBackend; business layer may extend with SQLite / PostgreSQL implementations.)
- agent.event_log.types::StructuredEvent, (POS: Single source of truth for event log data structures.)

[OUTPUT]
- SessionEvidenceExtractor: Background analyzer to mine hotspots and anti-patterns.

[POS]
Data mining engine for trace evidence. Runs periodically in idle_tasks
to analyze failed tool calls and user interruptions for skill evolution.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from .types import AntiPattern, EventFilter, FileHotspot, TraceRunDigest

if TYPE_CHECKING:
    from .protocols import EventLogBackend

logger = logging.getLogger(__name__)

_FILE_READ_TOOLS = frozenset({"file_read_tool"})
_FILE_WRITE_TOOLS = frozenset({"file_write_tool", "file_edit_tool"})
_PATH_HOTSPOT_TOOLS = _FILE_READ_TOOLS | _FILE_WRITE_TOOLS | frozenset({"grep_tool"})


def _resolve_tool_path(data: dict[str, object]) -> str:
    for key in ("path", "file_path"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


class SessionEvidenceExtractor:
    """Extracts trace evidence (hotspots and anti-patterns) from raw traces."""

    def __init__(self, backend: EventLogBackend) -> None:
        self._backend = backend

    async def extract_digest(self, session_id: str) -> TraceRunDigest | None:
        """Extract a single trace digest for a completed session."""
        events = await self._backend.get_events(session_id, EventFilter())
        if not events:
            return None

        hotspots: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {"read_count": 0, "write_count": 0, "last_accessed": 0.0}
        )
        anti_patterns: list[AntiPattern] = []

        task_intent: str | None = None
        duration_ms = 0.0
        success_rate = 1.0  # Heuristic: 1.0 minus penalty for errors

        start_time = 0.0
        error_count = 0
        total_tools = 0

        # Simple state tracking for anti-pattern extraction
        # If a tool fails, and shortly after there's a user_interruption,
        # or it is never retried successfully, it's an anti-pattern.
        last_failed_tool: dict[str, Any] | None = None

        for event in events:
            et = event.event_type
            data = event.data

            if et == "session_start":
                start_time = event.timestamp
                # Attempt to extract intent
                task_input = data.get("task_input") or data.get("query") or data.get("message")
                if isinstance(task_input, str):
                    task_intent = task_input[:200]  # First 200 chars as intent

            elif et == "session_end":
                if start_time:
                    duration_ms = (event.timestamp - start_time) * 1000

            elif et == "tool_start":
                total_tools += 1
                tool_name = data.get("tool_name")
                if isinstance(tool_name, str) and tool_name in _PATH_HOTSPOT_TOOLS:
                    file_path = _resolve_tool_path(data)
                    if file_path:
                        hs = hotspots[file_path]
                        if tool_name in _FILE_READ_TOOLS or tool_name == "grep_tool":
                            hs["read_count"] = int(hs["read_count"]) + 1
                        else:
                            hs["write_count"] = int(hs["write_count"]) + 1
                        hs["last_accessed"] = event.timestamp

            elif et == "tool_failure" or et == "error":
                error_count += 1
                tool_name = str(data.get("tool_name", "unknown"))
                error_msg = str(data.get("error") or data.get("error_message") or "")
                # Only record distinct/substantial errors as anti-patterns
                if tool_name != "unknown" and len(error_msg) > 5:
                    last_failed_tool = {
                        "name": tool_name,
                        "args": {
                            k: v for k, v in data.items() if not k.startswith("_") and k != "tool_name" and k != "error"
                        },
                        "error": error_msg[:500],
                        "ts": event.timestamp,
                    }
                    # Immediately add as anti-pattern; if user corrects it later, we'll update it.
                    anti_patterns.append(
                        AntiPattern(
                            error_signature=error_msg[:200],
                            failed_tool=tool_name,
                            failed_args=last_failed_tool["args"],
                            user_correction=None,
                            timestamp=event.timestamp,
                        )
                    )

            elif et == "user_interruption":
                # User interrupted or took over.
                # If there was a recent failed tool, tie this correction to it.
                correction = str(data.get("correction_message", data.get("message", "User aborted/took over.")))
                # Update the last anti-pattern (within 5 mins of the last failed tool)
                if last_failed_tool and (event.timestamp - last_failed_tool["ts"]) < 300 and anti_patterns:
                    last_ap = anti_patterns[-1]
                    anti_patterns[-1] = AntiPattern(
                        error_signature=last_ap.error_signature,
                        failed_tool=last_ap.failed_tool,
                        failed_args=last_ap.failed_args,
                        user_correction=correction[:500],
                        timestamp=last_ap.timestamp,
                    )

        # Calculate success rate heuristic
        if total_tools > 0:
            success_rate = max(0.0, 1.0 - (error_count / total_tools))

        # Convert hotspots dict to list
        hotspots_list = [
            FileHotspot(
                file_path=k,
                read_count=int(v["read_count"]),
                write_count=int(v["write_count"]),
                last_accessed=float(v["last_accessed"]),
            )
            for k, v in hotspots.items()
        ]
        # Sort by most written, then most read
        hotspots_list.sort(key=lambda x: (x.write_count, x.read_count), reverse=True)

        return TraceRunDigest(
            session_id=session_id,
            task_intent=task_intent,
            hotspots=hotspots_list[:20],  # Keep top 20
            anti_patterns=anti_patterns[-10:],  # Keep last 10
            success_rate=success_rate,
            duration_ms=duration_ms,
        )

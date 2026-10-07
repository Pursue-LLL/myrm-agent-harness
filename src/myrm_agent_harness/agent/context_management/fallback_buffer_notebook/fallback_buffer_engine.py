"""Core engine for Auto-Compact Fallback Buffer and Team Notebook Suite (Item 223).

[INPUT]
- Current token headroom measurements and context window specifications.
- TeamNotebookEntry records written by cooperating subagents.
- FallbackBufferConfig: Reserved buffer bounds and fallback templates.

[OUTPUT]
- FallbackBufferNotebookEngine: Orchestrates watermark guards, team scratchpads, and compaction banners.
- BufferWatermarkSnapshot: Real-time headroom telemetry and fallback triggering state.
- TeamNotebookSnapshot: Consolidated multi-agent handoff markdown.
- CompactionConsequenceAlert: Transparent human-in-the-loop notification.

[POS]
- Safeguards mission-critical workflows from fatal context OOMs via reserve buffers
- and streamlines multi-agent relay tasks without repeating historical context.
"""

from __future__ import annotations

import datetime
import threading
import time
import uuid

from .fallback_buffer_types import (
    BufferWatermarkSnapshot,
    BufferWatermarkState,
    CompactionConsequenceAlert,
    FallbackBufferConfig,
    TeamNotebookEntry,
    TeamNotebookSnapshot,
)


class FallbackBufferNotebookEngine:
    """Manages token headroom safety buffers, team scratchpads, and compaction transparency."""

    def __init__(self, config: FallbackBufferConfig | None = None) -> None:
        self._config: FallbackBufferConfig = config or FallbackBufferConfig()
        self._notebooks: dict[str, list[TeamNotebookEntry]] = {}
        self._alerts: dict[str, list[CompactionConsequenceAlert]] = {}
        self._lock: threading.Lock = threading.Lock()

    @property
    def config(self) -> FallbackBufferConfig:
        """Returns the active configuration."""
        return self._config

    def assess_watermark(self, current_tokens: int) -> BufferWatermarkSnapshot:
        """Evaluates proximity to physical context ceiling and assesses fallback trigger state.

        Args:
            current_tokens: Active token count across current context window.

        Returns:
            BufferWatermarkSnapshot detailing headroom, utilization, and watermark state.
        """
        limit = self._config.context_window_limit
        buffer_tokens = self._config.fallback_buffer_tokens
        safe_ceiling = max(0, limit - buffer_tokens)
        remaining = max(0, limit - current_tokens)
        utilization = min(1.0, round(current_tokens / max(1, limit), 4))

        if current_tokens >= limit:
            state = BufferWatermarkState.CRITICAL_EXHAUSTED
        elif current_tokens >= safe_ceiling:
            state = BufferWatermarkState.FALLBACK_TRIGGERED
        elif current_tokens >= int(safe_ceiling * self._config.warning_threshold_ratio):
            state = BufferWatermarkState.WARNING_APPROACHING
        else:
            state = BufferWatermarkState.SAFE

        return BufferWatermarkSnapshot(
            current_tokens=current_tokens,
            context_window_limit=limit,
            fallback_buffer_tokens=buffer_tokens,
            safe_ceiling_tokens=safe_ceiling,
            watermark_state=state,
            utilization_ratio=utilization,
            remaining_buffer_tokens=remaining,
        )

    def is_fallback_compaction_required(self, current_tokens: int) -> bool:
        """Fast probe checking whether active tokens have breached the safe ceiling.

        When True, the caller MUST initiate fallback compaction using the reserved buffer.
        """
        safe_ceiling = self._config.context_window_limit - self._config.fallback_buffer_tokens
        return current_tokens >= safe_ceiling

    def generate_fallback_compact_instruction(
        self,
        snapshot: BufferWatermarkSnapshot,
        custom_prompt: str | None = None,
    ) -> str:
        """Constructs an emergency fallback prompt utilizing the reserved buffer allowance.

        Args:
            snapshot: Current watermark telemetry.
            custom_prompt: Optional prompt override.

        Returns:
            Formatted instructional prompt for emergency fallback compaction.
        """
        base_prompt = custom_prompt or self._config.default_fallback_prompt
        lines: list[str] = [
            "<emergency_fallback_compaction>",
            f"[Headroom Status]: Current {snapshot.current_tokens} tokens breached safe ceiling {snapshot.safe_ceiling_tokens}.",
            f"[Reserved Safety Buffer]: {snapshot.fallback_buffer_tokens} tokens allocated to execute this compaction safely.",
            "[Directive]:",
            base_prompt,
            "[Preservation Mandate]:",
            "- Retain confirmed architectural decisions, key file diff summaries, and active blockers.",
            "- Purge voluminous command logs, test stdout, and redundant pleasantries.",
            "</emergency_fallback_compaction>",
        ]
        return "\n".join(lines)

    def append_notebook_entry(self, entry: TeamNotebookEntry) -> TeamNotebookSnapshot:
        """Appends a task milestone entry to the shared team workspace scratchpad.

        Args:
            entry: Strongly typed note authored by a subagent.

        Returns:
            TeamNotebookSnapshot with updated compiled markdown.
        """
        with self._lock:
            if entry.session_id not in self._notebooks:
                self._notebooks[entry.session_id] = []
            self._notebooks[entry.session_id].append(entry)

        return self.read_notebook_snapshot(entry.session_id)

    def read_notebook_snapshot(self, session_id: str) -> TeamNotebookSnapshot:
        """Compiles the shared multi-agent scratchpad into structured Markdown.

        Args:
            session_id: Target session identifier.

        Returns:
            TeamNotebookSnapshot allowing subsequent subagents to align instantly.
        """
        with self._lock:
            entries = list(self._notebooks.get(session_id, []))

        if not entries:
            return TeamNotebookSnapshot(
                session_id=session_id,
                total_notes=0,
                compiled_markdown="# Team Shared Scratchpad\n*(No entries recorded yet)*",
                last_updated_by="",
            )

        # Sort chronologically by subtask_index then timestamp
        sorted_entries = sorted(entries, key=lambda e: (e.subtask_index, e.timestamp))
        last_worker = sorted_entries[-1].agent_role

        md_lines: list[str] = [
            f"# Team Shared Scratchpad [{session_id}]",
            f"**Total Checkpoints**: {len(sorted_entries)} | **Last Updated By**: `{last_worker}`",
            "",
            "## Work Progress Log",
        ]

        for e in sorted_entries:
            time_str = datetime.datetime.fromtimestamp(
                e.timestamp, tz=datetime.timezone.utc
            ).strftime("%H:%M:%S UTC")
            md_lines.extend(
                [
                    f"### [{time_str}] Subtask #{e.subtask_index}: {e.section_title} (`{e.agent_role}`)",
                    e.content.strip(),
                    "",
                ]
            )

        compiled = "\n".join(md_lines)
        return TeamNotebookSnapshot(
            session_id=session_id,
            total_notes=len(sorted_entries),
            compiled_markdown=compiled,
            last_updated_by=last_worker,
        )

    def generate_compaction_alert(
        self,
        session_id: str,
        snapshot: BufferWatermarkSnapshot,
        compacted_turn_range: str,
        preserved_decision_summary: str,
        archived_ledger_ref: str = "sqlite://session_action_ledger",
    ) -> CompactionConsequenceAlert:
        """Generates a transparent user notification alert detailing compaction consequences.

        Args:
            session_id: Target session identifier.
            snapshot: Triggering watermark state.
            compacted_turn_range: String identifying compacted turns (e.g. 'Turns 1-14').
            preserved_decision_summary: Synopsis of preserved milestones.
            archived_ledger_ref: URI or pointer to fine-grained action ledger.

        Returns:
            CompactionConsequenceAlert record suitable for UI banner display.
        """
        alert_id = f"alert_compaction_{uuid.uuid4().hex[:8]}"
        banner = (
            f"⚠️ [Auto-Compact Safe Guard Activated]: Active context reached {snapshot.current_tokens}/"
            f"{snapshot.context_window_limit} tokens. Compacted {compacted_turn_range}. "
            f"Preserved key decisions: '{preserved_decision_summary}'. "
            f"Full raw technical steps archived in {archived_ledger_ref}."
        )

        alert = CompactionConsequenceAlert(
            alert_id=alert_id,
            session_id=session_id,
            trigger_tokens=snapshot.current_tokens,
            compacted_turn_range=compacted_turn_range,
            preserved_decision_summary=preserved_decision_summary,
            archived_ledger_ref=archived_ledger_ref,
            user_banner_text=banner,
        )

        with self._lock:
            if session_id not in self._alerts:
                self._alerts[session_id] = []
            self._alerts[session_id].append(alert)

        return alert

    def get_session_alerts(self, session_id: str) -> list[CompactionConsequenceAlert]:
        """Returns all compaction alerts issued for a session."""
        with self._lock:
            return list(self._alerts.get(session_id, []))

    def clear_session(self, session_id: str) -> None:
        """Cleans up notebook entries and alerts for a given session."""
        with self._lock:
            self._notebooks.pop(session_id, None)
            self._alerts.pop(session_id, None)

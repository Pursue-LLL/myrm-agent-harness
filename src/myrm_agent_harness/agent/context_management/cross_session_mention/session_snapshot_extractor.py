"""Extractor of immutable read-only snapshots from historical session records.

[INPUT]
- CrossSessionConfig: Limits on snapshot token budget and turn fallbacks.
- SessionRecord: Raw historical session state and logs.
- SessionSnapshot: Output distilled read-only data model.

[OUTPUT]
- SessionSnapshotExtractor: Pure transformer extracting safe, read-only session snapshots.

[POS]
Data distillation and budget protection layer for cross-session referencing.
"""

from __future__ import annotations

from typing import Sequence

from .cross_session_types import CrossSessionConfig, SessionRecord, SessionSnapshot


class SessionSnapshotExtractor:
    """Extracts compact, read-only snapshots from archived session records under strict token caps."""

    def __init__(self, config: CrossSessionConfig | None = None) -> None:
        self._config = config or CrossSessionConfig()

    def extract_snapshot(self, session: SessionRecord) -> SessionSnapshot:
        """Distills session record into an immutable SessionSnapshot respecting token budgets."""
        # 1. Determine summary content: prefer compacted_summary, fallback to recent turns
        summary_body: str
        if session.compacted_summary and session.compacted_summary.strip():
            summary_body = session.compacted_summary.strip()
        elif session.recent_messages:
            summary_body = self._build_recent_turns_fallback(
                session.recent_messages, self._config.fallback_recent_turns
            )
        else:
            summary_body = "(No summarized state or recent conversation available.)"

        # 2. Key artifacts
        artifacts_summary = list(session.artifacts)

        # 3. Assemble combined text representation to check budget
        raw_combined = self._format_snapshot_text(summary_body, artifacts_summary)
        token_cap = self._config.max_snapshot_tokens_per_session
        char_cap = token_cap * 4

        truncated_summary = summary_body
        if len(raw_combined) > char_cap:
            truncation_notice = "\n... [Truncated to Token Budget] ..."
            allowed_len = max(0, char_cap - len(truncation_notice) - 100)
            truncated_summary = summary_body[:allowed_len] + truncation_notice

        # Recompute final token estimate
        final_text = self._format_snapshot_text(truncated_summary, artifacts_summary)
        estimated_tokens = max(1, (len(final_text) + 3) // 4)

        reference_badge = f"🔗 引用了会话《{session.title}》只读快照"

        return SessionSnapshot(
            session_id=session.session_id,
            title=session.title,
            summary_content=truncated_summary,
            key_artifacts=tuple(artifacts_summary),
            is_read_only=True,
            token_estimate=estimated_tokens,
            reference_badge=reference_badge,
        )

    @staticmethod
    def _build_recent_turns_fallback(
        messages: Sequence[Mapping[str, str]], max_turns: int
    ) -> str:
        """Renders trailing N conversation turns as a fallback summary block."""
        selected = messages[-max_turns:] if len(messages) > max_turns else messages
        lines: list[str] = ["[Recent Turn History (Fallback)]"]
        for msg in selected:
            role = msg.get("role", "unknown").capitalize()
            content = msg.get("content", "").strip()
            # Collapse internal multiline content for brevity
            one_line_content = " ".join(content.split())
            lines.append(f"- {role}: {one_line_content}")
        return "\n".join(lines)

    @staticmethod
    def _format_snapshot_text(summary: str, artifacts: Sequence[str]) -> str:
        parts: list[str] = [summary]
        if artifacts:
            parts.append("\nKey Artifacts:\n" + "\n".join(f"- {a}" for a in artifacts))
        return "\n".join(parts)

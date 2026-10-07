from __future__ import annotations

import uuid

from myrm_agent_harness.agent.streaming.graceful_interruption_types import (
    GracefulInterruptionReport,
    InterruptedArtifactSnapshot,
    SeamlessStitchedPromptBlock,
)


class PartialArtifactFlushPipeline:
    """Pipelines safely flushing partial in-progress artifacts and seamlessly stitching subsequent context."""

    def __init__(self, max_snippet_chars: int = 1000) -> None:
        self._staged_artifacts: list[InterruptedArtifactSnapshot] = []
        self._max_snippet_chars = max_snippet_chars

    def register_partial_artifact(
        self,
        name: str,
        artifact_type: str,
        content: str,
        artifact_id: str | None = None,
        meta: dict[str, str] | None = None,
    ) -> InterruptedArtifactSnapshot:
        """Stage an in-progress code modification or draft artifact before completion."""
        aid = artifact_id or f"partial-{uuid.uuid4().hex[:8]}"
        snippet = (
            content[: self._max_snippet_chars]
            if len(content) <= self._max_snippet_chars
            else content[: self._max_snippet_chars] + "\n...[truncated snippet]..."
        )
        snapshot = InterruptedArtifactSnapshot(
            artifact_id=aid,
            name=name,
            artifact_type=artifact_type,
            content_snippet=snippet,
            bytes_length=len(content.encode("utf-8")),
            is_partially_flushed=True,
            meta=dict(meta or {}),
        )
        self._staged_artifacts.append(snapshot)
        return snapshot

    def flush_partial_artifacts(self) -> list[InterruptedArtifactSnapshot]:
        """Commit and safely flush all registered partial artifacts."""
        flushed = list(self._staged_artifacts)
        self._staged_artifacts.clear()
        return flushed

    def stitch_preempted_context(
        self,
        report: GracefulInterruptionReport,
    ) -> SeamlessStitchedPromptBlock:
        """Render seamless transition prompt block stitching preserved artifacts with user preemptive input."""
        lines: list[str] = [
            "<system_turn_interruption_handoff>",
            f"[STATUS]: Prior turn {report.turn_index} was gracefully interrupted at step "
            f"{report.step_index_interrupted}/{report.total_planned_steps} due to '{report.signal_kind.value}'.",
        ]

        if report.preempting_user_message:
            lines.append(f"[PREEMPTING_USER_INPUT]:\n{report.preempting_user_message.strip()}")

        if report.executed_tool_summaries:
            lines.append("[SUCCESSFULLY_EXECUTED_TOOLS]:")
            for summary in report.executed_tool_summaries:
                lines.append(f"  - {summary}")

        if report.preserved_artifacts:
            lines.append("[PRESERVED_PARTIAL_ARTIFACTS]:")
            for art in report.preserved_artifacts:
                lines.append(
                    f"  - [{art.artifact_type}] {art.name} (id={art.artifact_id}, size={art.bytes_length} bytes):"
                )
                indented_snippet = "\n".join(f"      {line}" for line in art.content_snippet.splitlines())
                lines.append(indented_snippet)

        lines.extend([
            "[CONTINUATION_DIRECTIVE]:",
            "  Do not re-execute the preserved tools or re-generate already preserved artifacts.",
            "  Immediately pivot and incorporate the preempting user input to advance toward the revised goal.",
            "</system_turn_interruption_handoff>",
        ])

        xml_content = "\n".join(lines)
        summary = (
            f"Turn {report.turn_index} interrupted at step {report.step_index_interrupted} "
            f"with {len(report.preserved_artifacts)} preserved artifacts and "
            f"{len(report.executed_tool_summaries)} completed tool steps."
        )

        return SeamlessStitchedPromptBlock(
            rendered_context_xml=xml_content,
            summary_digest=summary,
        )

    def clear(self) -> None:
        """Clear any staged artifacts."""
        self._staged_artifacts.clear()

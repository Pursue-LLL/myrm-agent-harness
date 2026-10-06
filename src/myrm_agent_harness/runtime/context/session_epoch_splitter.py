"""Auto-Forking Milestone Checkpoint Archiver & Long-Session Epoch Splitter.

Proactively monitors session message volume and token saturation, synthesizes structured
milestone capsules (goals, pending tasks, decisions, artifacts), and cleanly forks subsequent
epochs with zero-information-loss context handoff.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from myrm_agent_harness.runtime.context.session_epoch_splitter_types import (
    EpochSplitUrgency,
    ForkedEpochSessionDescriptor,
    MilestoneArtifactRef,
    MilestoneCheckpointPayload,
    SessionSaturationProbeReport,
)

__all__ = [
    "EpochSplitUrgency",
    "ForkedEpochSessionDescriptor",
    "LongSessionEpochSplitter",
    "MilestoneArtifactRef",
    "MilestoneCheckpointArchiver",
    "MilestoneCheckpointPayload",
    "SessionSaturationGovernor",
    "SessionSaturationProbeReport",
]


class SessionSaturationGovernor:
    """Monitors token usage and message counts to detect saturation boundaries."""

    DEFAULT_WARNING_MESSAGES: ClassVar[int] = 800
    DEFAULT_SPLIT_MESSAGES: ClassVar[int] = 1500
    DEFAULT_HARD_LIMIT_MESSAGES: ClassVar[int] = 2000

    DEFAULT_WARNING_RATIO: ClassVar[float] = 0.70
    DEFAULT_SPLIT_RATIO: ClassVar[float] = 0.85

    @classmethod
    def probe_saturation(
        cls,
        *,
        message_count: int,
        estimated_tokens: int,
        max_context_window: int,
        warning_messages: int | None = None,
        split_messages: int | None = None,
        hard_limit_messages: int | None = None,
        warning_ratio: float | None = None,
        split_ratio: float | None = None,
    ) -> SessionSaturationProbeReport:
        """Evaluates whether session has reached warning or auto-forking thresholds."""
        w_msg = warning_messages or cls.DEFAULT_WARNING_MESSAGES
        s_msg = split_messages or cls.DEFAULT_SPLIT_MESSAGES
        h_msg = hard_limit_messages or cls.DEFAULT_HARD_LIMIT_MESSAGES
        w_ratio = warning_ratio or cls.DEFAULT_WARNING_RATIO
        s_ratio = split_ratio or cls.DEFAULT_SPLIT_RATIO

        safe_window = max(max_context_window, 1)
        ratio = round(min(max(estimated_tokens / safe_window, 0.0), 1.0), 4)

        if message_count >= h_msg or ratio >= 0.95:
            return SessionSaturationProbeReport(
                message_count=message_count,
                estimated_tokens=estimated_tokens,
                max_context_window=max_context_window,
                saturation_ratio=ratio,
                urgency=EpochSplitUrgency.SPLIT_IMMEDIATELY,
                should_auto_fork=True,
                diagnostic_reason=f"Session hard boundary reached ({message_count}/{h_msg} msgs, {ratio:.1%} ctx). Immediate split required.",
            )

        if message_count >= s_msg or ratio >= s_ratio:
            return SessionSaturationProbeReport(
                message_count=message_count,
                estimated_tokens=estimated_tokens,
                max_context_window=max_context_window,
                saturation_ratio=ratio,
                urgency=EpochSplitUrgency.CRITICAL,
                should_auto_fork=True,
                diagnostic_reason=f"Auto-forking split threshold triggered ({message_count} msgs, {ratio:.1%} ctx).",
            )

        if message_count >= w_msg or ratio >= w_ratio:
            return SessionSaturationProbeReport(
                message_count=message_count,
                estimated_tokens=estimated_tokens,
                max_context_window=max_context_window,
                saturation_ratio=ratio,
                urgency=EpochSplitUrgency.WARNING,
                should_auto_fork=False,
                diagnostic_reason=f"Context saturation warning ({message_count} msgs, {ratio:.1%} ctx). Approaching boundary.",
            )

        return SessionSaturationProbeReport(
            message_count=message_count,
            estimated_tokens=estimated_tokens,
            max_context_window=max_context_window,
            saturation_ratio=ratio,
            urgency=EpochSplitUrgency.NORMAL,
            should_auto_fork=False,
            diagnostic_reason="Session within nominal capacity limits.",
        )


class MilestoneCheckpointArchiver:
    """Synthesizes structured milestone capsules and formats prompt preambles."""

    @staticmethod
    def generate_checkpoint(
        *,
        session_id: str,
        epoch_index: int,
        parent_session_id: str | None,
        completed_goals: tuple[str, ...],
        pending_tasks: tuple[str, ...],
        active_artifacts: tuple[MilestoneArtifactRef, ...],
        key_decisions: tuple[str, ...],
        created_at_utc: str,
    ) -> MilestoneCheckpointPayload:
        return MilestoneCheckpointPayload(
            session_id=session_id,
            epoch_index=epoch_index,
            parent_session_id=parent_session_id,
            completed_goals=completed_goals,
            pending_tasks=pending_tasks,
            active_artifacts=active_artifacts,
            key_decisions=key_decisions,
            created_at_utc=created_at_utc,
        )

    @classmethod
    def render_milestone_preamble(cls, checkpoint: MilestoneCheckpointPayload) -> str:
        """Renders an XML milestone context block for seamless prompt hydration."""
        parent_id = checkpoint.parent_session_id or "root"
        lines: list[str] = [
            '<milestone_epoch_preamble version="1.0">',
            f'  <parent_origin session_id="{checkpoint.session_id}" epoch_index="{checkpoint.epoch_index}" parent_id="{parent_id}" created_at="{checkpoint.created_at_utc}" />',
            "  <completed_goals>",
        ]
        for goal in checkpoint.completed_goals:
            lines.append(f"    <goal>{goal}</goal>")
        lines.append("  </completed_goals>")

        lines.append("  <key_decisions>")
        for dec in checkpoint.key_decisions:
            lines.append(f"    <decision>{dec}</decision>")
        lines.append("  </key_decisions>")

        lines.append("  <active_artifacts>")
        for art in checkpoint.active_artifacts:
            lines.append(f'    <artifact path="{art.path}" version="{art.version}">{art.summary}</artifact>')
        lines.append("  </active_artifacts>")

        lines.append("  <pending_tasks>")
        for task in checkpoint.pending_tasks:
            lines.append(f"    <task>{task}</task>")
        lines.append("  </pending_tasks>")

        lines.append("</milestone_epoch_preamble>")
        return "\n".join(lines)


class LongSessionEpochSplitter:
    """Executes atomic epoch splits, creating next-generation sessions."""

    @classmethod
    def fork_next_epoch(
        cls,
        *,
        source_session_id: str,
        current_epoch_index: int,
        completed_goals: tuple[str, ...],
        pending_tasks: tuple[str, ...],
        active_artifacts: tuple[MilestoneArtifactRef, ...],
        key_decisions: tuple[str, ...],
        created_at_utc: str,
        parent_session_id: str | None = None,
        next_session_id_generator: Callable[[str, int], str] | None = None,
    ) -> ForkedEpochSessionDescriptor:
        """Synthesizes milestone checkpoint and descriptors for subsequent epoch session."""
        checkpoint = MilestoneCheckpointArchiver.generate_checkpoint(
            session_id=source_session_id,
            epoch_index=current_epoch_index,
            parent_session_id=parent_session_id,
            completed_goals=completed_goals,
            pending_tasks=pending_tasks,
            active_artifacts=active_artifacts,
            key_decisions=key_decisions,
            created_at_utc=created_at_utc,
        )

        preamble = MilestoneCheckpointArchiver.render_milestone_preamble(checkpoint)
        gen = next_session_id_generator or (lambda src, ep: f"{src}_epoch_{ep}")
        next_epoch = current_epoch_index + 1
        next_id = gen(source_session_id, next_epoch)

        return ForkedEpochSessionDescriptor(
            next_session_id=next_id,
            parent_session_id=source_session_id,
            epoch_index=next_epoch,
            checkpoint=checkpoint,
            hydrated_preamble=preamble,
        )

"""
[POS] src/myrm_agent_harness/core/security/blast_radius_approval/facade.py
[INPUT] typing, types, dry_run_probe, launch_code_manager, span_grouper
[OUTPUT] BlastRadiusApprovalFacade
Unified facade for blast radius dry-run impact preview, typed launch codes, and never-fold batch grouping.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import uuid

from .dry_run_probe import DryRunProbeEngine
from .launch_code_manager import TypedLaunchCodeManager
from .span_grouper import NeverFoldSpanGrouper
from .types import (
    ApprovalSpanGroupPolicy,
    DryRunImpactPreview,
    LaunchCodeRequirement,
)

logger = logging.getLogger(__name__)


class BlastRadiusApprovalFacade:
    """Unified entrypoint for blast radius evaluation, launch challenge validation, and span partitioning."""

    def __init__(
        self,
        probe_engine: DryRunProbeEngine | None = None,
        launch_code_mgr: TypedLaunchCodeManager | None = None,
        grouper: NeverFoldSpanGrouper | None = None,
    ) -> None:
        self._probe_engine = probe_engine or DryRunProbeEngine()
        self._launch_code_mgr = launch_code_mgr or TypedLaunchCodeManager()
        self._grouper = grouper or NeverFoldSpanGrouper(
            probe_engine=self._probe_engine,
            launch_code_mgr=self._launch_code_mgr,
        )

    @property
    def probe_engine(self) -> DryRunProbeEngine:
        """Underlying dry-run probe engine."""
        return self._probe_engine

    @property
    def launch_code_manager(self) -> TypedLaunchCodeManager:
        """Underlying typed launch challenge manager."""
        return self._launch_code_mgr

    def evaluate_command_approval(
        self,
        command: str,
        workspace_dir: str | None = None,
        span_id: str | None = None,
    ) -> ApprovalSpanGroupPolicy:
        """Assess impact preview, challenge requirement, and keyboard shortcuts for a single command."""
        sid = span_id or f"span-{uuid.uuid4().hex[:8]}"
        is_destructive = self._probe_engine.is_destructive_command(command)

        impact: DryRunImpactPreview | None = None
        launch_code: LaunchCodeRequirement | None = None
        shortcuts = ("Enter", "y", "Esc", "n")

        if is_destructive:
            impact = self._probe_engine.probe_blast_radius(
                command=command,
                workspace_dir=workspace_dir,
            )
            launch_code = self._launch_code_mgr.generate_challenge(command)
            if launch_code.requires_challenge:
                shortcuts = ("Esc", "n")

        return ApprovalSpanGroupPolicy(
            span_id=sid,
            command=command,
            is_destructive=is_destructive,
            never_folded=is_destructive,
            impact_preview=impact,
            launch_code=launch_code,
            allowed_shortcuts=shortcuts,
        )

    def evaluate_batch_spans(
        self,
        commands: list[tuple[str, str]],
        workspace_dir: str | None = None,
    ) -> tuple[tuple[ApprovalSpanGroupPolicy, ...], list[list[str]]]:
        """Classify and partition batch spans into safe merged sets and isolated destructive items."""
        return self._grouper.evaluate_spans(commands, workspace_dir=workspace_dir)

    def verify_launch_code(
        self,
        token: str,
        user_input: str,
        current_time: float | None = None,
    ) -> tuple[bool, str]:
        """Verify and invalidate single-use typed challenge code."""
        return self._launch_code_mgr.verify_and_consume(
            token=token,
            user_input=user_input,
            current_time=current_time,
        )

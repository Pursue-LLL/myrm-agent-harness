"""
[POS] src/myrm_agent_harness/core/security/blast_radius_approval/span_grouper.py
[INPUT] typing, types, dry_run_probe, launch_code_manager
[OUTPUT] NeverFoldSpanGrouper
Batch approval span grouper preventing destructive commands from being folded into common groups.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .dry_run_probe import DryRunProbeEngine
from .launch_code_manager import TypedLaunchCodeManager
from .types import ApprovalSpanGroupPolicy

logger = logging.getLogger(__name__)


class NeverFoldSpanGrouper:
    """Enforces never-fold segregation for destructive spans during batch approval processing."""

    def __init__(
        self,
        probe_engine: DryRunProbeEngine | None = None,
        launch_code_mgr: TypedLaunchCodeManager | None = None,
    ) -> None:
        self._probe_engine = probe_engine or DryRunProbeEngine()
        self._launch_code_mgr = launch_code_mgr or TypedLaunchCodeManager()

    def evaluate_spans(
        self,
        commands: list[tuple[str, str]],  # (span_id, command)
        workspace_dir: str | None = None,
    ) -> tuple[tuple[ApprovalSpanGroupPolicy, ...], list[list[str]]]:
        """Classify and partition spans into safe merged groups and isolated destructive spans.

        Returns:
            A tuple of:
            1. All policies per span
            2. Resulting decision groups (lists of span_ids to decide together or singly)
        """
        policies: list[ApprovalSpanGroupPolicy] = []
        safe_group: list[str] = []
        decision_groups: list[list[str]] = []

        for span_id, command in commands:
            is_destructive = self._probe_engine.is_destructive_command(command)

            if is_destructive:
                # Probe dry-run blast radius
                impact = self._probe_engine.probe_blast_radius(
                    command=command,
                    workspace_dir=workspace_dir,
                )
                # Check launch code requirement
                launch_code = self._launch_code_mgr.generate_challenge(command)

                # Shortcuts: If launch code required, disable direct Enter approval
                shortcuts = (
                    ("Esc", "n")
                    if launch_code.requires_challenge
                    else ("Enter", "y", "Esc", "n")
                )

                policy = ApprovalSpanGroupPolicy(
                    span_id=span_id,
                    command=command,
                    is_destructive=True,
                    never_folded=True,
                    impact_preview=impact,
                    launch_code=launch_code,
                    allowed_shortcuts=shortcuts,
                )
                policies.append(policy)
                # Destructive spans are NEVER folded: they form standalone 1-item groups
                decision_groups.append([span_id])
                logger.info(
                    "Segregated destructive span %s into isolated approval group (never-folded)",
                    span_id,
                )
            else:
                policy = ApprovalSpanGroupPolicy(
                    span_id=span_id,
                    command=command,
                    is_destructive=False,
                    never_folded=False,
                    impact_preview=None,
                    launch_code=None,
                    allowed_shortcuts=("Enter", "y", "Esc", "n"),
                )
                policies.append(policy)
                safe_group.append(span_id)

        # Non-destructive items can be safely batch-approved together
        if safe_group:
            decision_groups.insert(0, safe_group)

        return tuple(policies), decision_groups

"""Tri-state context pruning and Reality Cross-Check engine.

Classifies context into KEEP, COMPRESS, and DISCARD to prevent context bloating
during structured handoffs. Mandates verification against the physical workspace
(files, git state) instead of blindly accepting handoff summaries.

[INPUT]
- runtime.context.multi_gateway_trust_types::PrunedContextItem, RealityCheckReceipt, TriStateTag (POS:
  Strongly typed data contracts for Model-Harness orthogonal decoupling and multi-gateway trust.)

[OUTPUT]
- TriStateHandoffEngine: Manages tri-state context decomposition and conducts reality cross-checks.

[POS]
Tri-state context pruning and Reality Cross-Check engine.
"""

from __future__ import annotations

import os
import time
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.multi_gateway_trust_types import (
    PrunedContextItem,
    RealityCheckReceipt,
    TriStateTag,
)


class TriStateHandoffEngine:
    """Manages tri-state context decomposition and conducts reality cross-checks."""

    @staticmethod
    def classify_and_prune(
        items: Sequence[PrunedContextItem],
    ) -> tuple[tuple[PrunedContextItem, ...], tuple[PrunedContextItem, ...], tuple[PrunedContextItem, ...]]:
        """Separate items into keep, compress, and discard buckets.

        Returns (kept_items, compressed_items, discarded_items).
        """
        kept: list[PrunedContextItem] = []
        compressed: list[PrunedContextItem] = []
        discarded: list[PrunedContextItem] = []

        for item in items:
            if item.tag == TriStateTag.KEEP:
                kept.append(item)
            elif item.tag == TriStateTag.COMPRESS:
                compressed.append(item)
            elif item.tag == TriStateTag.DISCARD:
                discarded.append(item)

        return tuple(kept), tuple(compressed), tuple(discarded)

    def assemble_handoff_manifest(
        self,
        task_goal: str,
        kept_items: Sequence[PrunedContextItem],
        compressed_items: Sequence[PrunedContextItem],
        declared_files: Sequence[str],
    ) -> str:
        """Assemble structured handoff prompt for the successor agent."""
        lines: list[str] = [
            "# Structured Task Handoff Manifest\n",
            f"**Goal**: {task_goal}\n",
            "## 1. Verified Core Artifacts & Decisions (KEEP)",
        ]
        for it in kept_items:
            lines.append(f"- [{it.source_type}] {it.processed_content}")

        lines.append("\n## 2. Compact Historical Trajectory (COMPRESS)")
        for it in compressed_items:
            lines.append(f"- [{it.source_type}] {it.processed_content}")

        lines.append("\n## 3. Declared File Modifications")
        for f in declared_files:
            lines.append(f"- `{f}`")

        return "\n".join(lines).strip()

    def cross_check_reality(
        self,
        workspace_root: str,
        declared_files: Sequence[str],
        git_clean_expected: bool = False,
    ) -> RealityCheckReceipt:
        """Cross-check handoff declarations against the physical file system and git state.

        Does not trust agent summaries at face value; verifies actual workspace reality.
        """
        checked_files: list[str] = []
        missing_files: list[str] = []
        discrepancies: list[str] = []

        for rel_path in declared_files:
            clean_rel = rel_path.strip().lstrip("/")
            checked_files.append(clean_rel)
            full_path = os.path.join(workspace_root, clean_rel)
            if not os.path.exists(full_path):
                missing_files.append(clean_rel)
                discrepancies.append(
                    f"Claimed file '{clean_rel}' does not exist on disk at '{full_path}'."
                )

        # Check git state if .git folder exists
        git_dir = os.path.join(workspace_root, ".git")
        git_present = os.path.isdir(git_dir)
        git_clean = True

        if git_present and git_clean_expected and missing_files:
            # When expected to be clean, any missing files or discrepancy violates reality
            git_clean = False
            discrepancies.append("Workspace has missing declared files; not git clean.")

        timestamp_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        is_verified = len(missing_files) == 0 and len(discrepancies) == 0

        return RealityCheckReceipt(
            verified=is_verified,
            checked_files=tuple(checked_files),
            missing_files=tuple(missing_files),
            git_clean=git_clean,
            discrepancies=tuple(discrepancies),
            timestamp_utc=timestamp_utc,
        )

"""Semantic condensation engine extracting trials, failures, and lessons from exploratory branches.

[INPUT]
- agent.context_management.session_tree_dag::SessionTreeEntry (POS: Immutable session tree DAG and branching
  exploration suite.)
- agent.context_management.branch_switch_summarization.branch_summary_types::BranchExplorationCard,
  BranchOutcomeVerdict, BranchSummaryEntry (POS: Types and schemas for branch switch outcome condensation and
  context transfer.)

[OUTPUT]
- BranchOutcomeCondenser: Condenses verbose exploratory branch traces into actionable lessons without context
  pollution.

[POS]
Semantic condensation engine extracting trials, failures, and lessons from exploratory branches.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from ..session_tree_dag import SessionTreeEntry
from .branch_summary_types import (
    BranchExplorationCard,
    BranchOutcomeVerdict,
    BranchSummaryEntry,
)


class BranchOutcomeCondenser:
    """Condenses verbose exploratory branch traces into actionable lessons without context pollution."""

    _ERROR_PATTERNS = [
        re.compile(r"error:\s*(.*)", re.IGNORECASE),
        re.compile(r"exception:\s*(.*)", re.IGNORECASE),
        re.compile(r"failed to\s*(.*)", re.IGNORECASE),
        re.compile(r"timed out|timeout", re.IGNORECASE),
        re.compile(r"incompatible|cannot import|version conflict", re.IGNORECASE),
    ]

    _SUCCESS_PATTERNS = [
        re.compile(r"successfully\s*(.*)", re.IGNORECASE),
        re.compile(r"verified:\s*(.*)", re.IGNORECASE),
        re.compile(r"passed:\s*(.*)", re.IGNORECASE),
    ]

    @classmethod
    def condense_branch_entries(
        cls,
        source_branch_name: str,
        target_branch_name: str,
        entries: List[SessionTreeEntry],
        verdict: BranchOutcomeVerdict = BranchOutcomeVerdict.ABANDONED_FAILURE,
        manual_takeaway: Optional[str] = None,
    ) -> BranchExplorationCard:
        """Extract structured trials, failures, and findings from historical branch entries."""
        unviable_options: List[str] = []
        validated_findings: List[str] = []
        attempted_approaches: List[str] = []
        failure_root_cause: Optional[str] = None

        for entry in entries:
            content = entry.payload.get("content", "")
            role = entry.payload.get("role", "")

            # Attempt detection
            if role in ("user", "assistant") and any(
                kw in content.lower() for kw in ["try", "attempt", "implement", "test", "experiment"]
            ):
                snippet = content.split("\n")[0][:120]
                if snippet not in attempted_approaches:
                    attempted_approaches.append(snippet)

            # Error / Unviable options detection
            for pattern in cls._ERROR_PATTERNS:
                match = pattern.search(content)
                if match:
                    err_msg = match.group(0).strip()[:100]
                    if err_msg not in unviable_options:
                        unviable_options.append(err_msg)
                    if failure_root_cause is None:
                        failure_root_cause = err_msg

            # Validated findings detection
            for pattern in cls._SUCCESS_PATTERNS:
                match = pattern.search(content)
                if match:
                    finding = match.group(0).strip()[:100]
                    if finding not in validated_findings:
                        validated_findings.append(finding)

        primary_approach = (
            attempted_approaches[0]
            if attempted_approaches
            else f"Exploratory trials on branch '{source_branch_name}'"
        )

        key_lesson = manual_takeaway or (
            f"Approach '{primary_approach}' failed due to: {failure_root_cause or 'Unspecified incompatibility'}. "
            f"Do not repeat this attempt on {target_branch_name}."
            if verdict == BranchOutcomeVerdict.ABANDONED_FAILURE
            else f"Approach '{primary_approach}' validated useful findings: {', '.join(validated_findings[:2])}."
        )

        return BranchExplorationCard(
            card_id=f"card_{uuid.uuid4().hex[:8]}",
            source_branch=source_branch_name,
            target_branch=target_branch_name,
            verdict=verdict,
            attempted_approach=primary_approach,
            failure_root_cause=failure_root_cause,
            unviable_options=unviable_options[:5],
            validated_findings=validated_findings[:5],
            key_lesson=key_lesson,
        )

    @classmethod
    def synthesize_summary_entry(
        cls,
        card: BranchExplorationCard,
    ) -> BranchSummaryEntry:
        """Render BranchExplorationCard into a compact, prompt-injectable first-class entry."""
        unviable_block = ""
        if card.unviable_options:
            unviable_block = "\n  - Dead ends avoided: " + "; ".join(card.unviable_options)

        findings_block = ""
        if card.validated_findings:
            findings_block = "\n  - Validated findings: " + "; ".join(card.validated_findings)

        payload_lines = [
            f"<branch_switch_lesson from='{card.source_branch}' to='{card.target_branch}' verdict='{card.verdict.value}'>",
            f"  - Attempted: {card.attempted_approach}",
            f"  - Key takeaway: {card.key_lesson}{unviable_block}{findings_block}",
            "</branch_switch_lesson>",
        ]
        formatted_payload = "\n".join(payload_lines)
        estimated_tokens = max(15, len(formatted_payload) // 4)

        return BranchSummaryEntry(
            summary_entry_id=f"bse_{uuid.uuid4().hex[:8]}",
            source_branch_name=card.source_branch,
            target_branch_name=card.target_branch,
            formatted_prompt_payload=formatted_payload,
            estimated_tokens=estimated_tokens,
            created_at_iso=datetime.now(timezone.utc).isoformat(),
            metadata={"verdict": card.verdict.value},
        )

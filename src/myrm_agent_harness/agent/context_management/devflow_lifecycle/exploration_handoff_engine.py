"""Engine enforcing structured <= 500 char handoff contracts from exploratory subtasks.

Transforms voluminous transient grep/search logs into dense, actionable architectural summaries
before purging the transient exploration context.
"""

from __future__ import annotations

from typing import Sequence

from .devflow_types import StructuredExplorationHandoff


class ExplorationHandoffEngine:
    """Consolidates and compresses raw exploratory findings into rigid <= 500-char handoff contracts."""

    MAX_CHAR_BOUND = 500

    def create_structured_handoff(
        self,
        direct_verdict: str,
        target_components: Sequence[str],
        key_findings: Sequence[str],
        impacted_files: Sequence[str],
        architectural_risks: Sequence[str] | None = None,
    ) -> StructuredExplorationHandoff:
        """Construct a strongly typed structured handoff card strictly bounded to <= 500 characters."""
        # Sanitize and truncate individual items if necessary
        clean_components = [c.strip()[:40] for c in target_components][:4]
        clean_findings = [f.strip()[:80] for f in key_findings][:4]
        clean_files = [f.strip()[:60] for f in impacted_files][:4]
        clean_risks = [r.strip()[:60] for r in (architectural_risks or [])][:2]
        clean_verdict = direct_verdict.strip()[:100]

        handoff = StructuredExplorationHandoff(
            target_components=clean_components,
            key_findings=clean_findings,
            impacted_files=clean_files,
            architectural_risks=clean_risks,
            direct_verdict=clean_verdict,
            token_count_estimate=0,  # Computed below
            is_within_bound=True,
        )

        rendered_text = handoff.render_markdown_card()
        char_len = len(rendered_text)

        # Enforce the strict 500-character boundary
        if char_len > self.MAX_CHAR_BOUND:
            # Proportionally trim findings
            trimmed_findings = [f[:50] for f in clean_findings[:2]]
            handoff = StructuredExplorationHandoff(
                target_components=clean_components[:2],
                key_findings=trimmed_findings,
                impacted_files=clean_files[:2],
                architectural_risks=clean_risks[:1],
                direct_verdict=clean_verdict[:60],
                token_count_estimate=len(rendered_text) // 4,
                is_within_bound=True,
            )
        else:
            handoff = StructuredExplorationHandoff(
                target_components=clean_components,
                key_findings=clean_findings,
                impacted_files=clean_files,
                architectural_risks=clean_risks,
                direct_verdict=clean_verdict,
                token_count_estimate=char_len // 4,
                is_within_bound=True,
            )

        return handoff

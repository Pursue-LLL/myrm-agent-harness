"""Custom Compaction Directives and Preservation Whitelist Suite master class.

Unifies configuration parsing, prompt slot injection, post-compaction integrity auditing,
and automatic self-healing patches to guarantee 100% domain fact retention across compactions.
"""

from __future__ import annotations

from typing import Sequence

from .compaction_directives_injector import CompactionDirectivesInjector
from .compaction_directives_types import (
    CompactionIntegrityReport,
    CustomCompactionConfig,
    PreservationDirective,
)
from .preservation_whitelist_auditor import PreservationWhitelistAuditor


class CustomCompactionDirectivesAndPreservationWhitelistSuite:
    """Master suite orchestrating user-defined compaction preservation rules and self-healing."""

    def __init__(self, config: CustomCompactionConfig | None = None) -> None:
        self.config = config or CustomCompactionConfig()
        self._injector = CompactionDirectivesInjector()
        self._auditor = PreservationWhitelistAuditor()
        self._reports: list[CompactionIntegrityReport] = []

    @property
    def injector(self) -> CompactionDirectivesInjector:
        """Access the underlying prompt directives injector."""
        return self._injector

    @property
    def auditor(self) -> PreservationWhitelistAuditor:
        """Access the underlying whitelist auditor."""
        return self._auditor

    def parse_directives_markdown(self, markdown_text: str) -> list[PreservationDirective]:
        """Extract structured directives from a 'Compact instructions' block."""
        return self._injector.parse_from_markdown_block(markdown_text)

    def prepare_compaction_prompt(
        self,
        base_prompt: str,
        directives: Sequence[PreservationDirective],
    ) -> str:
        """Inject domain preservation instructions into the summarizer prompt template."""
        return self._injector.inject_into_prompt(base_prompt, directives)

    def audit_and_heal_summary(
        self,
        generated_summary: dict[str, object] | str,
        raw_context: str,
        directives: Sequence[PreservationDirective],
        session_id: str = "sess-default",
    ) -> tuple[dict[str, object] | str, CompactionIntegrityReport]:
        """Perform post-compaction entity verification and apply automatic self-healing patches."""
        final_summary, report = self._auditor.audit_and_heal(
            generated_summary=generated_summary,
            raw_context=raw_context,
            directives=directives,
            session_id=session_id,
            auto_heal=self.config.auto_heal_missing,
        )
        self._reports.append(report)
        return final_summary, report

    def get_aggregate_telemetry(self) -> dict[str, object]:
        """Produce cumulative metrics on directive retention and self-healing frequency."""
        total_runs = len(self._reports)
        healed_runs = sum(1 for r in self._reports if r.was_healed)
        avg_retention = (
            sum(r.retention_rate for r in self._reports) / total_runs
            if total_runs > 0
            else 1.0
        )

        return {
            "total_compactions_audited": total_runs,
            "compactions_self_healed": healed_runs,
            "average_directives_retention_rate": round(avg_retention, 4),
            "perfect_retention_ratio": 1.0 if total_runs == 0 or avg_retention >= 1.0 else round(avg_retention, 4),
        }

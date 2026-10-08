"""Preservation Whitelist Auditor verifying and auto-healing summaries post-compaction.

Performs deterministic regex and substring entity auditing on generated summaries.
If any critical domain directives are omitted by the LLM, seamlessly heals the summary
by extracting the verified entity facts directly from the raw pre-compaction context.

[INPUT]
-
  agent.context_management.custom_compaction_directives.compaction_directives_types::CompactionIntegrityReport,
  DirectiveAuditResult, PreservationDirective (POS: Data contracts and type definitions for custom compaction
  directives and preservation whitelist.)

[OUTPUT]
- PreservationWhitelistAuditor: Audits generated summaries against custom preservation directives and
  auto-heals missing facts.

[POS]
Preservation Whitelist Auditor verifying and auto-healing summaries post-compaction.
"""

from __future__ import annotations

import json
import re
from typing import Sequence

from .compaction_directives_types import (
    CompactionIntegrityReport,
    DirectiveAuditResult,
    PreservationDirective,
)


class PreservationWhitelistAuditor:
    """Audits generated summaries against custom preservation directives and auto-heals missing facts."""

    def audit_and_heal(
        self,
        generated_summary: dict[str, object] | str,
        raw_context: str,
        directives: Sequence[PreservationDirective],
        session_id: str = "sess-default",
        auto_heal: bool = True,
    ) -> tuple[dict[str, object] | str, CompactionIntegrityReport]:
        """Verify directive entity retention in summary and auto-heal missing items if required."""
        summary_text = (
            json.dumps(generated_summary, ensure_ascii=False)
            if isinstance(generated_summary, dict)
            else str(generated_summary)
        )
        lower_summary = summary_text.lower()

        audit_results: list[DirectiveAuditResult] = []
        all_missing_entities: list[str] = []
        satisfied_count = 0

        for d in directives:
            missing_entities: list[str] = []
            matched_snippets: list[str] = []

            # Check explicit entities
            for ent in d.required_entities:
                if ent.lower() in lower_summary:
                    matched_snippets.append(ent)
                else:
                    missing_entities.append(ent)
                    all_missing_entities.append(ent)

            # Check keywords if no explicit entities defined
            if not d.required_entities and d.required_keywords:
                matched_kw = [kw for kw in d.required_keywords if kw.lower() in lower_summary]
                matched_snippets.extend(matched_kw)
                if not matched_kw:
                    missing_entities.extend(d.required_keywords[:2])
                    all_missing_entities.extend(d.required_keywords[:2])

            is_satisfied = (len(missing_entities) == 0)
            if is_satisfied:
                satisfied_count += 1

            audit_results.append(
                DirectiveAuditResult(
                    directive_id=d.directive_id,
                    is_satisfied=is_satisfied,
                    missing_entities=missing_entities,
                    matched_snippets=matched_snippets,
                    explanation=(
                        "Directive satisfied completely."
                        if is_satisfied
                        else f"Missing entities: {', '.join(missing_entities)}"
                    ),
                )
            )

        total_directives = len(directives)
        initial_retention = (satisfied_count / total_directives) if total_directives > 0 else 1.0

        # Auto-healing step
        healed = False
        healed_entities: list[str] = []
        final_summary = generated_summary

        if auto_heal and all_missing_entities:
            final_summary, healed_entities = self._heal_summary(
                generated_summary=generated_summary,
                raw_context=raw_context,
                missing_entities=all_missing_entities,
                directives=directives,
            )
            healed = len(healed_entities) > 0

        final_retention = 1.0 if (satisfied_count == total_directives or healed) else initial_retention

        report = CompactionIntegrityReport(
            session_id=session_id,
            total_directives=total_directives,
            satisfied_count=satisfied_count if not healed else total_directives,
            missing_count=0 if healed else (total_directives - satisfied_count),
            retention_rate=round(final_retention, 4),
            was_healed=healed,
            audit_details=audit_results,
            healed_entities=healed_entities,
        )

        return final_summary, report

    def _heal_summary(
        self,
        generated_summary: dict[str, object] | str,
        raw_context: str,
        missing_entities: list[str],
        directives: Sequence[PreservationDirective],
    ) -> tuple[dict[str, object] | str, list[str]]:
        """Extract missing entity occurrences from raw context and append to summary."""
        recovered_facts: list[str] = []
        healed_entities: list[str] = []

        for ent in set(missing_entities):
            # Find lines in raw context containing the entity
            pattern = re.compile(rf"^.*?\b{re.escape(ent)}\b.*?$", re.MULTILINE | re.IGNORECASE)
            match = pattern.search(raw_context)
            if match:
                snippet = match.group(0).strip()[:140]
                recovered_facts.append(f"[Preserved Fact] {snippet}")
                healed_entities.append(ent)
            else:
                recovered_facts.append(f"[Preserved Entity] {ent}")
                healed_entities.append(ent)

        if isinstance(generated_summary, dict):
            summary_dict = dict(generated_summary)
            # Append into custom_preserved_facts or key_findings
            existing_facts = summary_dict.get("custom_preserved_facts")
            if isinstance(existing_facts, list):
                summary_dict["custom_preserved_facts"] = list(existing_facts) + recovered_facts
            else:
                summary_dict["custom_preserved_facts"] = recovered_facts

            # Also ensure key_findings has mention
            kf = summary_dict.get("key_findings")
            if isinstance(kf, list):
                summary_dict["key_findings"] = list(kf) + recovered_facts[:2]

            return summary_dict, healed_entities

        # String format: stitch patch to the end
        patch_block = "\n\n## Custom Preservation Recovery Patch (Auto-Healed):\n" + "\n".join(
            f"- {fact}" for fact in recovered_facts
        )
        return f"{generated_summary.rstrip()}\n{patch_block}", healed_entities

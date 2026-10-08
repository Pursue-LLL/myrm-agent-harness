"""MemoryManager mixin for knowledge graph pre-extraction content screening and injection shield.

[INPUT]
- toolkits.memory.kg_screening.shield::KnowledgeGraphPoisoningShield (POS: shield)
- toolkits.memory.kg_screening.types::ScreeningAuditRecord, ScreeningResult (POS: types)

[OUTPUT]
- MemoryManagerKGScreeningMixin: runtime orchestration methods for graph content pre-extraction screening and audit trail

[POS]
Partial mixin for MemoryManager providing pre-extraction prompt injection scanning, hidden HTML stripping, and anti-poisoning defenses.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.kg_screening.shield import (
        KnowledgeGraphPoisoningShield,
    )
    from myrm_agent_harness.toolkits.memory.kg_screening.types import (
        ScreeningAuditRecord,
        ScreeningResult,
    )


class MemoryManagerKGScreeningMixin:
    """Provides methods for screening text before knowledge graph extraction and querying security audit records."""

    def screen_kg_candidate_text(
        self,
        text: str,
        *,
        source_uri: str = "",
        sanitize_if_possible: bool = True,
        shield: KnowledgeGraphPoisoningShield | None = None,
    ) -> ScreeningResult:
        """Screen raw candidate text against prompt injection, steganography, and hidden HTML comments."""
        from myrm_agent_harness.toolkits.memory.kg_screening.shield import (
            KnowledgeGraphPoisoningShield,
        )

        active_shield = shield or KnowledgeGraphPoisoningShield()
        return active_shield.screen_text(
            text=text,
            source_uri=source_uri,
            sanitize_if_possible=sanitize_if_possible,
        )

    def list_kg_screening_audit_records(
        self,
        *,
        limit: int = 50,
        shield: KnowledgeGraphPoisoningShield | None = None,
    ) -> list[ScreeningAuditRecord]:
        """Fetch historical screening security audit records ordered newest first."""
        from myrm_agent_harness.toolkits.memory.kg_screening.shield import (
            KnowledgeGraphPoisoningShield,
        )

        active_shield = shield or KnowledgeGraphPoisoningShield()
        return active_shield.get_audit_records(limit=limit)

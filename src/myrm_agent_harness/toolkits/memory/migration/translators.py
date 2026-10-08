"""[POS]: src/myrm_agent_harness/toolkits/memory/migration/translators.py
[INPUT]: Competitor memory files and raw payload strings.
[OUTPUT]: UniversalMemoryTranslator facade normalizing diverse formats into canonical memory units.
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.memory.migration.models import (
    CompetitorSourceKind,
    NormalizedMemoryPayload,
)
from myrm_agent_harness.toolkits.memory.migration.parsers import (
    MultiPlatformParserMatrix,
)
from myrm_agent_harness.toolkits.memory.migration.security_guard import (
    MigrationSecurityGuard,
)


class UniversalMemoryTranslator:
    """Multi-source cognitive schema normalizer converting competitor data into canonical memory units."""

    def __init__(self, security_guard: MigrationSecurityGuard | None = None) -> None:
        self._parser_matrix = MultiPlatformParserMatrix(security_guard=security_guard)

    def translate_file(
        self, source_kind: CompetitorSourceKind, file_path: str | Path
    ) -> list[NormalizedMemoryPayload]:
        """Read external file and normalize into canonical memory payloads."""
        return self._parser_matrix.parse_file(
            source_type=source_kind,
            file_path=file_path,
        )

    def translate_raw(
        self,
        source_kind: CompetitorSourceKind,
        raw_text: str,
        source_id: str = "raw_input",
    ) -> list[NormalizedMemoryPayload]:
        """Normalize raw serialized text into structured memory payloads based on source kind."""
        return self._parser_matrix.parse_payload(
            source_type=source_kind,
            raw_content=raw_text,
            source_id=source_id,
        )

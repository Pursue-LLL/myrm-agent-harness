"""[POS]: src/myrm_agent_harness/toolkits/memory/migration/tools.py
[INPUT]: CompetitorMigrationService instance.
[OUTPUT]: Meta tools exposed to AI Agent for scanning and executing competitor memory migrations.
"""

from myrm_agent_harness.toolkits.memory.migration.models import (
    CompetitorSourceKind,
    DetectedCompetitorArtifact,
    MigrationExecutionReport,
)
from myrm_agent_harness.toolkits.memory.migration.service import (
    CompetitorMigrationService,
)


class CompetitorMigrationMetaTools:
    """Agent meta tools for discovering and importing competitor memory assets."""

    def __init__(self, service: CompetitorMigrationService) -> None:
        self._service = service

    def detect_competitor_memories(
        self, custom_search_paths: list[str] | None = None
    ) -> list[DetectedCompetitorArtifact]:
        """Scan local filesystem to discover candidate competitor memory archives."""
        return self._service.scan_local_artifacts(custom_candidates=custom_search_paths)

    def import_competitor_memory_artifact(
        self, source_kind: str, artifact_path: str
    ) -> MigrationExecutionReport:
        """Translate and ingest memory records from an external competitor file."""
        kind = CompetitorSourceKind(source_kind)
        return self._service.import_from_artifact(
            source_kind=kind, file_path=artifact_path
        )

    def import_competitor_memory_text(
        self, source_kind: str, raw_text: str, source_label: str = "raw_buffer"
    ) -> MigrationExecutionReport:
        """Translate and ingest memory records from an in-memory raw payload string."""
        kind = CompetitorSourceKind(source_kind)
        return self._service.import_raw_text(
            source_kind=kind, raw_text=raw_text, source_label=source_label
        )

    def get_migration_audit_history(self) -> list[MigrationExecutionReport]:
        """Retrieve audit history of previously executed memory migrations."""
        return self._service.list_migration_history()

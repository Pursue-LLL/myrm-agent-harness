"""MemoryManager mixin for third-party assistant asset detection and ingestion.

[INPUT]
- toolkits.memory.sovereign_migration.competitor_adapter::CompetitorIngestionAdapter (POS: competitor adapter)
- toolkits.memory.sovereign_migration.types::CompetitorDetectResult, CompetitorImportResult, CompetitorType (POS: contracts)

[OUTPUT]
- MemoryManagerSovereignMigrationMixin: runtime orchestration methods for competitor asset detection and ingestion

[POS]
Partial mixin for MemoryManager providing competitor asset detection and ingestion.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.sovereign_migration.competitor_adapter import (
        CompetitorIngestionAdapter,
    )
    from myrm_agent_harness.toolkits.memory.sovereign_migration.types import (
        CompetitorDetectResult,
        CompetitorImportResult,
        CompetitorType,
    )


class MemoryManagerSovereignMigrationMixin:
    """Provides methods for detecting and ingesting third-party assistant assets."""

    def detect_competitors(
        self,
        *,
        adapter: CompetitorIngestionAdapter | None = None,
        workspace_dir: Path | None = None,
    ) -> CompetitorDetectResult:
        """Probe host filesystem for third-party assistant configurations (Hermes, Claude Code, Codex)."""
        from myrm_agent_harness.toolkits.memory.sovereign_migration.competitor_adapter import (
            CompetitorIngestionAdapter,
        )

        active_adapter = adapter or CompetitorIngestionAdapter()
        return active_adapter.detect(workspace_root=workspace_dir)

    def ingest_competitor_assets(
        self,
        competitor: CompetitorType,
        source_path: Path | str,
        target_destination_dir: Path | str,
        *,
        adapter: CompetitorIngestionAdapter | None = None,
    ) -> CompetitorImportResult:
        """Translate third-party competitor memories, skills, and rules into Myrm standard layout."""
        from myrm_agent_harness.toolkits.memory.sovereign_migration.competitor_adapter import (
            CompetitorIngestionAdapter,
        )

        active_adapter = adapter or CompetitorIngestionAdapter()
        return active_adapter.ingest(
            competitor=competitor,
            source_path=source_path,
            target_destination_dir=target_destination_dir,
        )

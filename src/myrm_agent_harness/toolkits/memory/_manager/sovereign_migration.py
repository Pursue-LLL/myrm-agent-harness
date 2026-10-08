"""MemoryManager mixin for sovereign memory asset packaging, cross-host migration, and competitor ingestion.

[INPUT]
- toolkits.memory.sovereign_migration.bundle_archiver::SovereignBundleArchiver (POS: bundle exporter)
- toolkits.memory.sovereign_migration.bundle_restorer::SovereignBundleRestorer (POS: bundle restorer)
- toolkits.memory.sovereign_migration.competitor_adapter::CompetitorIngestionAdapter (POS: competitor adapter)
- toolkits.memory.sovereign_migration.types::CompetitorDetectResult, CompetitorImportResult, CompetitorType, ExportBundleRequest, ExportBundleResult, RestoreBundleRequest, RestoreBundleResult (POS: contracts)

[OUTPUT]
- MemoryManagerSovereignMigrationMixin: runtime orchestration methods for sovereign asset packaging and migration

[POS]
Partial mixin for MemoryManager providing atomic .myrmpkg bundle export, checksum-verified restore with path remapping, and competitor ingestion.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.sovereign_migration.bundle_archiver import (
        SovereignBundleArchiver,
    )
    from myrm_agent_harness.toolkits.memory.sovereign_migration.bundle_restorer import (
        SovereignBundleRestorer,
    )
    from myrm_agent_harness.toolkits.memory.sovereign_migration.competitor_adapter import (
        CompetitorIngestionAdapter,
    )
    from myrm_agent_harness.toolkits.memory.sovereign_migration.types import (
        CompetitorDetectResult,
        CompetitorImportResult,
        CompetitorType,
        ExportBundleRequest,
        ExportBundleResult,
        RestoreBundleRequest,
        RestoreBundleResult,
    )


class MemoryManagerSovereignMigrationMixin:
    """Provides methods for exporting and restoring sovereign memory bundles, and ingesting competitor assets."""

    def export_sovereign_bundle(
        self,
        request: ExportBundleRequest,
        *,
        archiver: SovereignBundleArchiver | None = None,
    ) -> ExportBundleResult:
        """Collect and package sovereign memory assets into verified portable .myrmpkg archive."""
        from myrm_agent_harness.toolkits.memory.sovereign_migration.bundle_archiver import (
            SovereignBundleArchiver,
        )

        active_archiver = archiver or SovereignBundleArchiver()
        return active_archiver.export_bundle(request)

    def restore_sovereign_bundle(
        self,
        request: RestoreBundleRequest,
        *,
        restorer: SovereignBundleRestorer | None = None,
    ) -> RestoreBundleResult:
        """Unpack .myrmpkg archive, verify SHA-256 checksums, and remap workspace paths."""
        from myrm_agent_harness.toolkits.memory.sovereign_migration.bundle_restorer import (
            SovereignBundleRestorer,
        )

        active_restorer = restorer or SovereignBundleRestorer()
        return active_restorer.restore_bundle(request)

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

"""Agent-facing LangChain tool for sovereign memory asset packaging, cross-host migration, and competitor ingestion.

[INPUT]
- toolkits.memory.sovereign_migration.bundle_archiver::SovereignBundleArchiver (POS: bundle exporter)
- toolkits.memory.sovereign_migration.bundle_restorer::SovereignBundleRestorer (POS: bundle restorer)
- toolkits.memory.sovereign_migration.competitor_adapter::CompetitorIngestionAdapter (POS: competitor adapter)
- toolkits.memory.sovereign_migration.types::AssetCategory, CompetitorType, ExportBundleRequest, RestoreBundleRequest (POS: contracts)

[OUTPUT]
- SovereignAssetActionInput: Pydantic input schema for sovereign asset migration tool
- create_sovereign_migration_tool: Factory creating LangChain BaseTool for Agent runtime

[POS]
Agent-facing LangChain tool allowing agents to detect external configs, export sovereign backup bundles, and restore memories across hosts.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

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
    AssetCategory,
    CompetitorType,
    ExportBundleRequest,
    RestoreBundleRequest,
)


class SovereignAssetActionInput(BaseModel):
    """Input payload for sovereign memory asset migration management."""

    action: str = Field(
        ...,
        description="Action to execute: 'detect' (probe third-party competitor files), 'export' (package sovereign .myrmpkg bundle), 'restore' (unpack and remap .myrmpkg), 'ingest' (translate competitor assets into Myrm)",
    )
    source_dir: str | None = Field(
        default=None,
        description="Source directory path for export or competitor ingestion",
    )
    output_bundle_path: str | None = Field(
        default=None,
        description="Target file path (.myrmpkg) to produce when exporting",
    )
    bundle_path: str | None = Field(
        default=None,
        description="Path to existing .myrmpkg bundle file to restore",
    )
    target_destination_dir: str | None = Field(
        default=None,
        description="Target destination directory for restored or ingested assets",
    )
    current_workspace_root: str | None = Field(
        default=None,
        description="Current host workspace root to remap paths to",
    )
    competitor_type: str | None = Field(
        default=None,
        description="Competitor platform identifier ('hermes', 'claude_code', 'codex')",
    )
    include_categories: list[str] | None = Field(
        default=None,
        description="List of asset categories to export ('wiki_memory', 'sqlite_database', 'handoff_record', 'custom_skill', 'agent_rule', 'unload_snapshot')",
    )


def create_sovereign_migration_tool(
    archiver: SovereignBundleArchiver | None = None,
    restorer: SovereignBundleRestorer | None = None,
    adapter: CompetitorIngestionAdapter | None = None,
) -> BaseTool:
    """Create a LangChain standard tool to manage sovereign asset migration and competitor ingestion."""
    active_archiver = archiver or SovereignBundleArchiver()
    active_restorer = restorer or SovereignBundleRestorer()
    active_adapter = adapter or CompetitorIngestionAdapter()

    @tool("manage_sovereign_memory_assets", args_schema=SovereignAssetActionInput)
    def manage_sovereign_memory_assets(
        action: str,
        source_dir: str | None = None,
        output_bundle_path: str | None = None,
        bundle_path: str | None = None,
        target_destination_dir: str | None = None,
        current_workspace_root: str | None = None,
        competitor_type: str | None = None,
        include_categories: list[str] | None = None,
    ) -> str:
        """Inspect competitor configs, export atomic verified .myrmpkg bundles, or restore sovereign memory assets across machines."""
        act = action.strip().lower()

        if act == "detect":
            discovered = active_adapter.detect(
                workspace_root=Path(current_workspace_root) if current_workspace_root else None
            )
            data = {
                "detected_competitors": [c.value for c in discovered.detected_competitors],
                "hermes_dir": discovered.hermes_dir,
                "claude_code_rule_path": discovered.claude_code_rule_path,
                "codex_rule_path": discovered.codex_rule_path,
            }
            return json.dumps({"action": "detect", "result": data}, ensure_ascii=False)

        if act == "export":
            if not source_dir or not output_bundle_path:
                return json.dumps({"error": "source_dir and output_bundle_path are required for export"}, ensure_ascii=False)
            cats: list[AssetCategory] | None = None
            if include_categories:
                cats = [AssetCategory(c) for c in include_categories if c in AssetCategory._value2member_map_]
            res = active_archiver.export_bundle(
                ExportBundleRequest(
                    source_dir=source_dir,
                    output_bundle_path=output_bundle_path,
                    include_categories=cats if cats is not None else [
                        AssetCategory.WIKI_MEMORY,
                        AssetCategory.SQLITE_DATABASE,
                        AssetCategory.HANDOFF_RECORD,
                        AssetCategory.UNLOAD_SNAPSHOT,
                        AssetCategory.AGENT_RULE,
                        AssetCategory.CUSTOM_SKILL,
                    ],
                )
            )
            return json.dumps(
                {
                    "action": "export",
                    "success": res.success,
                    "package_id": res.package_id,
                    "bundle_path": res.bundle_path,
                    "sha256": res.sha256,
                    "asset_count": res.asset_count,
                    "total_bytes": res.total_bytes,
                },
                ensure_ascii=False,
            )

        if act == "restore":
            if not bundle_path or not target_destination_dir:
                return json.dumps({"error": "bundle_path and target_destination_dir are required for restore"}, ensure_ascii=False)
            res_rest = active_restorer.restore_bundle(
                RestoreBundleRequest(
                    bundle_path=bundle_path,
                    target_destination_dir=target_destination_dir,
                    current_workspace_root=current_workspace_root or target_destination_dir,
                )
            )
            return json.dumps(
                {
                    "action": "restore",
                    "success": res_rest.success,
                    "package_id": res_rest.package_id,
                    "restored_assets": res_rest.restored_assets,
                    "remapped_paths_count": res_rest.remapped_paths_count,
                    "source_workspace_root": res_rest.source_workspace_root,
                    "target_workspace_root": res_rest.target_workspace_root,
                },
                ensure_ascii=False,
            )

        if act == "ingest":
            if not source_dir or not target_destination_dir or not competitor_type:
                return json.dumps({"error": "source_dir, target_destination_dir, and competitor_type are required for ingest"}, ensure_ascii=False)
            comp_enum = CompetitorType(competitor_type)
            res_ingest = active_adapter.ingest(
                competitor=comp_enum,
                source_path=source_dir,
                target_destination_dir=target_destination_dir,
            )
            return json.dumps(
                {
                    "action": "ingest",
                    "success": res_ingest.success,
                    "imported_rules_count": res_ingest.imported_rules_count,
                    "imported_skills_count": res_ingest.imported_skills_count,
                    "imported_memories_count": res_ingest.imported_memories_count,
                    "details": res_ingest.details,
                },
                ensure_ascii=False,
            )

        return json.dumps({"error": f"Unknown action '{action}'"}, ensure_ascii=False)

    return manage_sovereign_memory_assets

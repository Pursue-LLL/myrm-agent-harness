"""Agent-facing LangChain tool for third-party assistant asset detection and ingestion.

[INPUT]
- toolkits.memory.sovereign_migration.competitor_adapter::CompetitorIngestionAdapter (POS: competitor adapter)
- toolkits.memory.sovereign_migration.types::CompetitorType (POS: contracts)

[OUTPUT]
- SovereignAssetActionInput: Pydantic input schema for the competitor migration tool
- create_sovereign_migration_tool: Factory creating LangChain BaseTool for Agent runtime

[POS]
Agent-facing LangChain tool allowing agents to detect external assistant configs and translate them into Myrm assets.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.sovereign_migration.competitor_adapter import (
    CompetitorIngestionAdapter,
)
from myrm_agent_harness.toolkits.memory.sovereign_migration.types import CompetitorType


class SovereignAssetActionInput(BaseModel):
    """Input payload for competitor asset migration management."""

    action: str = Field(
        ...,
        description="Action to execute: 'detect' (probe third-party competitor files), 'ingest' (translate competitor assets into Myrm)",
    )
    source_dir: str | None = Field(
        default=None,
        description="Source path of the competitor assets to ingest",
    )
    target_destination_dir: str | None = Field(
        default=None,
        description="Target destination directory for ingested assets",
    )
    current_workspace_root: str | None = Field(
        default=None,
        description="Current workspace root probed for project-level rule files",
    )
    competitor_type: str | None = Field(
        default=None,
        description="Competitor platform identifier ('hermes', 'claude_code', 'codex')",
    )


def create_sovereign_migration_tool(
    adapter: CompetitorIngestionAdapter | None = None,
) -> BaseTool:
    """Create a LangChain standard tool to detect and ingest competitor assistant assets."""
    active_adapter = adapter or CompetitorIngestionAdapter()

    @tool("manage_sovereign_memory_assets", args_schema=SovereignAssetActionInput)
    def manage_sovereign_memory_assets(
        action: str,
        source_dir: str | None = None,
        target_destination_dir: str | None = None,
        current_workspace_root: str | None = None,
        competitor_type: str | None = None,
    ) -> str:
        """Inspect competitor configs and ingest their memories, skills and rules into Myrm."""
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

        if act == "ingest":
            if not source_dir or not target_destination_dir or not competitor_type:
                return json.dumps(
                    {"error": "source_dir, target_destination_dir, and competitor_type are required for ingest"},
                    ensure_ascii=False,
                )
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

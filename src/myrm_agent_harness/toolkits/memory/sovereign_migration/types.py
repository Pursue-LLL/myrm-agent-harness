"""Type definitions for sovereign asset bundle migration and cross-machine restore protocol.

Defines schemas for portable asset packaging, path relativization, checksum verification,
and competitor ingestion (Hermes, Claude Code, Codex).
Strict typing applied: No `Any` types allowed.

[INPUT]
- External: pydantic

[OUTPUT]
- AssetCategory: Categorization of sovereign assets included in the portable bundle.
- AssetEntry: Metadata describing a specific file or asset stored within the bundle.
- SovereignAssetManifest: Manifest header containing metadata and checksums of the sovereign package.
- ExportBundleRequest: Configuration requested to produce a portable sovereign asset bundle.
- ExportBundleResult: Summary outcome following completion of bundle creation.
- RestoreBundleRequest: Parameters provided to unpack and restore assets onto the target host.
- RestoreBundleResult: Outcome report following bundle verification and extraction.
- CompetitorType: Supported third-party competitor platforms for zero-friction migration.
- CompetitorDetectResult: Result of probing local environment for competitor data stores.
- CompetitorImportResult: Outcome summary after ingesting rules and memories from competitor setups.

[POS]
Type definitions for sovereign asset bundle migration and cross-machine restore protocol.
"""

from __future__ import annotations

import time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AssetCategory(StrEnum):
    """Categorization of sovereign assets included in the portable bundle."""

    WIKI_MEMORY = "wiki_memory"
    SQLITE_DATABASE = "sqlite_database"
    HANDOFF_RECORD = "handoff_record"
    UNLOAD_SNAPSHOT = "unload_snapshot"
    PROMPT_PLAYBOOK = "prompt_playbook"
    AGENT_RULE = "agent_rule"
    CUSTOM_SKILL = "custom_skill"


class AssetEntry(BaseModel):
    """Metadata describing a specific file or asset stored within the bundle."""

    model_config = ConfigDict(extra="forbid")

    category: AssetCategory = Field(..., description="Classification category of the asset")
    relative_path: str = Field(..., description="Relative file path within the bundle archive")
    sha256: str = Field(..., description="SHA-256 hexadecimal hash of the content")
    byte_size: int = Field(..., ge=0, description="Size of the uncompressed file in bytes")
    description: str = Field(default="", description="Human-readable description or title")


class SovereignAssetManifest(BaseModel):
    """Manifest header containing metadata and checksums of the sovereign package."""

    model_config = ConfigDict(extra="forbid")

    manifest_version: str = Field(default="1.0.0", description="Specification schema version")
    package_id: str = Field(..., description="Unique bundle identifier, e.g. myrmpkg-20261006-uuid")
    created_at: float = Field(default_factory=time.time, description="Unix timestamp of bundle generation")
    source_os: str = Field(..., description="Operating system platform where package was created: darwin, linux, win32")
    source_workspace_root: str = Field(..., description="Original workspace root path on exporting machine")
    description: str = Field(default="Myrm sovereign asset backup", description="User or automated description")
    assets: list[AssetEntry] = Field(default_factory=list, description="Collection of assets bundled")
    total_bytes: int = Field(default=0, ge=0, description="Aggregate byte size of all assets")
    manifest_sha256: str = Field(default="", description="Integrity hash computed across all asset records")


class ExportBundleRequest(BaseModel):
    """Configuration requested to produce a portable sovereign asset bundle."""

    model_config = ConfigDict(extra="forbid")

    source_dir: str = Field(..., min_length=1, description="Root directory containing .myrm data or workspace")
    output_bundle_path: str = Field(..., min_length=1, description="Target destination file path for .myrmpkg")
    include_categories: list[AssetCategory] = Field(
        default_factory=lambda: [
            AssetCategory.WIKI_MEMORY,
            AssetCategory.SQLITE_DATABASE,
            AssetCategory.HANDOFF_RECORD,
            AssetCategory.UNLOAD_SNAPSHOT,
            AssetCategory.AGENT_RULE,
            AssetCategory.CUSTOM_SKILL,
        ],
        description="Filter of asset categories to encompass",
    )
    custom_description: str = Field(default="Myrm portable asset backup", description="Annotation note")


class ExportBundleResult(BaseModel):
    """Summary outcome following completion of bundle creation."""

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(..., description="True if bundle archive was generated with integrity")
    bundle_path: str = Field(..., description="Final on-disk path to .myrmpkg archive")
    package_id: str = Field(..., description="Assigned package identifier")
    asset_count: int = Field(..., ge=0, description="Total number of items archived")
    total_bytes: int = Field(..., ge=0, description="Total uncompressed size in bytes")
    sha256: str = Field(..., description="SHA-256 hash of the generated bundle file")


class RestoreBundleRequest(BaseModel):
    """Parameters provided to unpack and restore assets onto the target host."""

    model_config = ConfigDict(extra="forbid")

    bundle_path: str = Field(..., min_length=1, description="Path to .myrmpkg archive on current host")
    target_destination_dir: str = Field(..., min_length=1, description="Target directory where assets are restored")
    current_workspace_root: str = Field(..., min_length=1, description="Active workspace path for dynamic remapping")
    overwrite_existing: bool = Field(default=False, description="Whether to overwrite existing files if conflicting")


class RestoreBundleResult(BaseModel):
    """Outcome report following bundle verification and extraction."""

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(..., description="True if verification and restoration concluded cleanly")
    package_id: str = Field(..., description="Package identifier restored")
    restored_assets: list[str] = Field(default_factory=list, description="List of relative file paths extracted")
    remapped_paths_count: int = Field(default=0, ge=0, description="Count of hardcoded path occurrences remapped")
    source_workspace_root: str = Field(..., description="Original workspace path recorded in manifest")
    target_workspace_root: str = Field(..., description="New active workspace path applied")


class CompetitorType(StrEnum):
    """Supported third-party competitor platforms for zero-friction migration."""

    HERMES = "hermes"
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"


class CompetitorDetectResult(BaseModel):
    """Result of probing local environment for competitor data stores."""

    model_config = ConfigDict(extra="forbid")

    detected_competitors: list[CompetitorType] = Field(
        default_factory=list, description="Competitor software recognized on host"
    )
    hermes_dir: str | None = Field(default=None, description="Discovered path to ~/.hermes if present")
    claude_code_rule_path: str | None = Field(default=None, description="Discovered path to CLAUDE.md if present")
    codex_rule_path: str | None = Field(default=None, description="Discovered path to AGENTS.md if present")


class CompetitorImportResult(BaseModel):
    """Outcome summary after ingesting rules and memories from competitor setups."""

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(..., description="True if import completed without fatal errors")
    imported_rules_count: int = Field(default=0, ge=0, description="Number of agent rules converted")
    imported_skills_count: int = Field(default=0, ge=0, description="Number of custom skills ingested")
    imported_memories_count: int = Field(default=0, ge=0, description="Number of memories/markdown pages created")
    details: list[str] = Field(default_factory=list, description="Detailed ingestion logs or status notices")

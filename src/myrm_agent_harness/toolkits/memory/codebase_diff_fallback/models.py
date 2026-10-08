"""Models and data structures for codebase memory large diff fallback.

Provides strongly-typed schemas for multi-tiered diff volume classification,
noise filtration, truncation safety guards, and aggregation fallback reports.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class DiffVolumeTier(StrEnum):
    """Execution tier determined by diff volume and truncation state."""

    MICRO = "micro"  # <= 20 files, <= 800 lines: Full AST & Symbol tracking
    MODERATE = "moderate"  # 21~100 files: Focus on core code, bypass noise
    LARGE = "large"  # 101~500 files: Architecture-level directory summary
    MASSIVE = "massive"  # > 500 files or API truncated: Top-level cluster aggregation


class DiffCategory(StrEnum):
    """Syntactic category of changed file paths."""

    CORE_CODE = "core_code"
    LOCKFILE = "lockfile"
    GENERATED = "generated"
    DOCUMENTATION = "documentation"
    CONFIG_INFRA = "config_infra"
    ASSET_BINARY = "asset_binary"


class DiffFileEntry(BaseModel):
    """Individual file change entry within a diff payload."""

    path: str = Field(description="Normalized relative path of the file")
    additions: int = Field(default=0, ge=0, description="Lines added")
    deletions: int = Field(default=0, ge=0, description="Lines deleted")
    category: DiffCategory = Field(
        default=DiffCategory.CORE_CODE,
        description="Classified syntactic category",
    )
    is_generated: bool = Field(default=False, description="Whether marked as generated/vendor")
    is_renamed: bool = Field(default=False, description="Whether file was renamed or moved")
    old_path: str | None = Field(default=None, description="Previous path if renamed")
    patch_snippet: str | None = Field(default=None, description="Raw or truncated patch snippet")

    @property
    def total_changes(self) -> int:
        """Total modified lines (additions + deletions)."""
        return self.additions + self.deletions


class DirectoryAggregate(BaseModel):
    """Aggregated diff metrics grouped by module or directory tree."""

    directory: str = Field(description="Top-level or module directory name")
    file_count: int = Field(ge=0, description="Number of files changed in directory")
    total_additions: int = Field(ge=0, description="Sum of additions")
    total_deletions: int = Field(ge=0, description="Sum of deletions")
    primary_category: DiffCategory = Field(
        default=DiffCategory.CORE_CODE,
        description="Dominant category in this directory",
    )


class LargeDiffFallbackConfig(BaseModel):
    """Configuration thresholds for diff tier evaluation and fallback."""

    micro_max_files: int = Field(default=20, ge=1)
    micro_max_lines: int = Field(default=800, ge=1)
    moderate_max_files: int = Field(default=100, ge=1)
    moderate_max_lines: int = Field(default=3000, ge=1)
    large_max_files: int = Field(default=500, ge=1)
    large_max_lines: int = Field(default=10000, ge=1)
    hard_file_cap: int = Field(
        default=3000,
        ge=10,
        description="Hard file count cap (aligning with codebase-memory #2269 3000-file cap)",
    )
    filter_lockfiles_in_moderate: bool = Field(default=True)
    token_budget: int = Field(default=4000, ge=100)


class DiffFallbackVerdict(BaseModel):
    """Complete diagnostic and synthesis verdict from diff processing."""

    tier: DiffVolumeTier = Field(description="Selected execution tier")
    total_files: int = Field(ge=0, description="Total files supplied")
    total_additions: int = Field(ge=0, description="Total additions across all files")
    total_deletions: int = Field(ge=0, description="Total deletions across all files")
    is_truncated: bool = Field(
        default=False,
        description="Whether diff list was truncated by API or exceeded hard cap",
    )
    truncation_reason: str | None = Field(
        default=None,
        description="Reason for truncation if triggered",
    )
    active_files_count: int = Field(
        ge=0,
        description="Count of active files retained for detailed indexing",
    )
    filtered_noise_files_count: int = Field(
        ge=0,
        description="Count of lockfiles/assets downgraded or bypassed",
    )
    directory_aggregates: list[DirectoryAggregate] = Field(
        default_factory=list,
        description="Aggregated changes by directory",
    )
    summary_text: str = Field(
        description="Consolidated summary text safe for memory context ingestion",
    )
    applied_optimizations: list[str] = Field(
        default_factory=list,
        description="List of applied fallback strategies and guards",
    )

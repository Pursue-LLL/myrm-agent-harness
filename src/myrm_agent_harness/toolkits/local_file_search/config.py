"""Configuration management for local file search toolkit.

[INPUT]
- .models::IndexedDirectory (POS: directory configuration model)

[OUTPUT]
- LocalFileSearchConfig: Main configuration with indexing parameters
- DEFAULT_EXCLUDE_PATTERNS: Sensible default exclusion patterns
- SUPPORTED_EXTENSIONS: File extensions the indexer can process

[POS]
Configuration for local file search. Manages indexed directories, exclusion rules,
chunking parameters, and collection naming. JSON-serializable via Pydantic for
persistence by the business layer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.local_file_search.models import IndexedDirectory

DEFAULT_EXCLUDE_PATTERNS: frozenset[str] = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".cache",
        ".next",
        ".nuxt",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "dist",
        "build",
        "target",
        "out",
        ".DS_Store",
        "Thumbs.db",
    }
)

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".rst",
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".pptx",
        ".ppt",
        ".csv",
        ".json",
        ".yaml",
        ".yml",
        ".xml",
        ".html",
        ".htm",
        ".py",
        ".js",
        ".ts",
        ".java",
        ".go",
        ".rs",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".sh",
        ".bash",
        ".zsh",
        ".sql",
        ".r",
        ".log",
        ".ini",
        ".cfg",
        ".conf",
        ".toml",
    }
)

VECTOR_COLLECTION_NAME = "local_file_search"

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


class LocalFileSearchConfig(BaseModel):
    """Main configuration for the local file search toolkit."""

    directories: list[IndexedDirectory] = Field(
        default_factory=list,
        description="User-configured directories to index",
    )
    exclude_patterns: list[str] = Field(
        default_factory=lambda: sorted(DEFAULT_EXCLUDE_PATTERNS),
        description="Directory/file name patterns to exclude",
    )
    max_file_size_bytes: int = Field(
        default=MAX_FILE_SIZE_BYTES,
        description="Skip files larger than this",
    )
    chunk_overlap_tokens: int = Field(
        default=50,
        ge=0,
        le=200,
        description="Token overlap between adjacent chunks",
    )

    def get_enabled_directories(self) -> list[IndexedDirectory]:
        """Return only enabled directories."""
        return [d for d in self.directories if d.enabled]

    def get_exclude_set(self) -> frozenset[str]:
        """Return exclusion patterns as a frozenset for O(1) lookup."""
        return frozenset(self.exclude_patterns)

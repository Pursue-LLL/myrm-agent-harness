"""Code Index configuration.

[INPUT]
dataclasses::dataclass, field (POS: standard library dataclass definition)

[OUTPUT]
CodeIndexConfig: Code indexing configuration dataclass

[POS]
Configuration for workspace code indexing. Controls indexing behavior, file
filters, search parameters, and resource limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset({
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".env",
    "env",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
    "out",
    ".idea",
    ".vscode",
    ".myrm",
    ".eggs",
    "vendor",
    "bower_components",
    "coverage",
    ".coverage",
    "htmlcov",
})

_DEFAULT_BINARY_EXTENSIONS: frozenset[str] = frozenset({
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".exe", ".bin",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".ico", ".webp", ".svg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".mp3", ".mp4", ".avi", ".mov", ".flv", ".wav", ".ogg",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".sqlite", ".db", ".mdb",
    ".lock",
})


@dataclass(frozen=True, slots=True)
class CodeIndexConfig:
    """Configuration for workspace code indexing.

    Attributes:
        max_file_size_bytes: Skip files larger than this (default 512KB).
        max_files: Maximum number of files to index per workspace.
        batch_size: Number of files to process per indexing batch.
        exclude_dirs: Directory names to skip during scanning.
        binary_extensions: File extensions to treat as binary and skip.
        enable_vector_search: Enable vector embedding for semantic search.
        fts_tokenizer: FTS5 tokenizer configuration.
        max_search_results: Maximum search results to return.
        index_db_name: Filename for the SQLite index database.
        collection_name: Vector store collection name for code chunks.
    """

    max_file_size_bytes: int = 512 * 1024
    max_files: int = 50_000
    batch_size: int = 100
    exclude_dirs: frozenset[str] = field(default_factory=lambda: _DEFAULT_EXCLUDE_DIRS)
    binary_extensions: frozenset[str] = field(default_factory=lambda: _DEFAULT_BINARY_EXTENSIONS)
    enable_vector_search: bool = True
    fts_tokenizer: str = 'unicode61 remove_diacritics 1'
    max_search_results: int = 20
    index_db_name: str = "code_index.db"
    collection_name: str = "code_chunks"

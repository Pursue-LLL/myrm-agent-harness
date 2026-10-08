"""Diff path classification and noise identification.

Categorizes file changes into core code, lockfiles, generated assets,
documentation, and infrastructure to enable intelligent filtering and fallback.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from .models import DiffCategory, DiffFileEntry

_LOCKFILE_NAMES: frozenset[str] = frozenset({
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "cargo.lock",
    "poetry.lock",
    "uv.lock",
    "composer.lock",
    "gemfile.lock",
    "go.sum",
    "mix.lock",
    "pipfile.lock",
})

_GENERATED_EXTENSIONS: frozenset[str] = frozenset({
    ".min.js",
    ".min.css",
    ".map",
    ".bundle.js",
    ".bundle.css",
})

_DOC_EXTENSIONS: frozenset[str] = frozenset({
    ".md",
    ".mdx",
    ".rst",
    ".txt",
    ".adoc",
})

_DOC_FILENAMES: frozenset[str] = frozenset({
    "license",
    "changelog",
    "contributing",
    "readme",
    "authors",
})

_ASSET_EXTENSIONS: frozenset[str] = frozenset({
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".bmp",
    ".tiff",
    ".wasm",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
})

_CONFIG_EXTENSIONS: frozenset[str] = frozenset({
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".env",
    ".dockerignore",
    ".gitignore",
    ".editorconfig",
})


class DiffPathClassifier:
    """Classifies file paths into categories to steer fallback decisions."""

    @staticmethod
    def classify_path(path: str) -> DiffCategory:
        """Determines the category of a file path."""
        normalized = path.replace("\\", "/").strip().lower()
        posix_path = PurePosixPath(normalized)
        filename = posix_path.name

        # 1. Lockfiles check
        if filename in _LOCKFILE_NAMES:
            return DiffCategory.LOCKFILE

        # 2. Generated and bundled code
        if any(normalized.endswith(ext) for ext in _GENERATED_EXTENSIONS):
            return DiffCategory.GENERATED
        if ".generated." in filename or filename.endswith("_pb2.py"):
            return DiffCategory.GENERATED

        # 3. Static assets & binaries
        if any(normalized.endswith(ext) for ext in _ASSET_EXTENSIONS):
            return DiffCategory.ASSET_BINARY

        # 4. Documentation
        if any(normalized.endswith(ext) for ext in _DOC_EXTENSIONS):
            return DiffCategory.DOCUMENTATION
        stem = posix_path.stem
        if stem in _DOC_FILENAMES or "docs/" in normalized:
            return DiffCategory.DOCUMENTATION

        # 5. Infrastructure & configuration
        if any(normalized.endswith(ext) for ext in _CONFIG_EXTENSIONS):
            return DiffCategory.CONFIG_INFRA
        if filename in {"dockerfile", "makefile", "gemfile", "procfile"}:
            return DiffCategory.CONFIG_INFRA
        if ".github/" in normalized or ".gitlab/" in normalized:
            return DiffCategory.CONFIG_INFRA

        # Default: Core source code
        return DiffCategory.CORE_CODE

    @classmethod
    def enrich_entry(cls, entry: DiffFileEntry) -> DiffFileEntry:
        """Returns a new or updated DiffFileEntry with classified category."""
        category = cls.classify_path(entry.path)
        is_gen = category in {DiffCategory.LOCKFILE, DiffCategory.GENERATED}
        return DiffFileEntry(
            path=entry.path,
            additions=entry.additions,
            deletions=entry.deletions,
            category=category,
            is_generated=entry.is_generated or is_gen,
            is_renamed=entry.is_renamed,
            old_path=entry.old_path,
            patch_snippet=entry.patch_snippet,
        )

    @staticmethod
    def extract_top_directory(path: str) -> str:
        """Extracts the top-level directory or module prefix from path."""
        normalized = path.replace("\\", "/").strip()
        parts = normalized.split("/")
        if len(parts) > 1:
            return parts[0]
        return "."

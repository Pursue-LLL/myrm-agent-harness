"""Trailing slash directory delineator for unambiguous filesystem path contracts.

Injects explicit trailing slash ('/') delimiters on directory matches in virtual
and sandbox filesystems, ensuring downstream agents and LLM tools never confuse
directories with regular files or attempt invalid text read operations.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .vfs_boundary_types import VFSPathKind


class TrailingSlashDelineator:
    """Provides path normalization and explicit trailing slash directory delineation."""

    @staticmethod
    def normalize_separators(path: str) -> str:
        """Converts backslashes to forward slashes and collapses redundant separators."""
        if not path:
            return ""
        # Convert backslashes
        normalized = path.replace("\\", "/")
        # Collapse multiple slashes (e.g. "a//b///c" -> "a/b/c"), preserving leading slash if root
        is_absolute = normalized.startswith("/")
        stripped = re.sub(r"/+", "/", normalized)
        if is_absolute and not stripped.startswith("/"):
            return "/" + stripped
        return stripped

    @classmethod
    def delineate_path(cls, path: str, is_dir: bool) -> str:
        """Delineates a path, ensuring directories end with '/' and files do not."""
        cleaned = cls.normalize_separators(path)
        if not cleaned:
            return "/" if is_dir else ""

        if is_dir:
            return cleaned if cleaned.endswith("/") else f"{cleaned}/"
        return cleaned.rstrip("/")

    @classmethod
    def is_delineated_dir(cls, path: str) -> bool:
        """Checks purely syntactically whether a path is marked as a directory."""
        cleaned = cls.normalize_separators(path)
        return cleaned.endswith("/")

    @classmethod
    def strip_delineation(cls, path: str) -> str:
        """Safely removes trailing slashes for low-level OS operations, except root '/'."""
        cleaned = cls.normalize_separators(path)
        if cleaned == "/":
            return "/"
        return cleaned.rstrip("/")

    @classmethod
    def classify_by_marker(cls, path: str) -> VFSPathKind:
        """Classifies path kind syntactically based on the trailing slash marker."""
        return (
            VFSPathKind.DIRECTORY
            if cls.is_delineated_dir(path)
            else VFSPathKind.FILE
        )

    @classmethod
    def batch_delineate(
        cls,
        items: Sequence[tuple[str, bool]],
    ) -> tuple[str, ...]:
        """Batch delineates a sequence of (path, is_dir) tuples."""
        return tuple(cls.delineate_path(p, is_dir) for p, is_dir in items)

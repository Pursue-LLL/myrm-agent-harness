"""Dynamic path relativization and cross-machine absolute path remapping engine.

Unbinds host-specific absolute file paths during asset export by translating them into
portable `${MYRM_WORKSPACE}` placeholders, and dynamically binds them to current host paths
during restoration to completely eliminate FileNotFoundError crashes.
Strict typing applied: No `Any` types allowed.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- PathRelativizer: Pure heuristic path relativization and cross-machine remapping engine.

[POS]
Dynamic path relativization and cross-machine absolute path remapping engine.
"""

from __future__ import annotations

import re
from pathlib import Path


class PathRelativizer:
    """Pure heuristic path relativization and cross-machine remapping engine."""

    WORKSPACE_PLACEHOLDER = "${MYRM_WORKSPACE}"

    @classmethod
    def relativize_text(cls, text: str, source_root: Path | str) -> tuple[str, int]:
        """Replace occurrences of source workspace absolute root with portable placeholder.

        Args:
            text: Text content (Markdown, JSON, logs, configurations).
            source_root: Original workspace root directory path on exporting host.

        Returns:
            Tuple of (relativized text, replacement count).
        """
        if not text:
            return "", 0

        source_str = str(Path(source_root).resolve())
        norm_source = source_str.replace("\\", "/")

        candidate_sources: list[str] = [norm_source]
        if norm_source.startswith("/private/var/"):
            candidate_sources.append(norm_source[len("/private") :])
        elif norm_source.startswith("/var/"):
            candidate_sources.append("/private" + norm_source)

        total_count = 0
        replaced_text = text.replace("\\", "/")

        for cand in candidate_sources:
            pattern = re.compile(re.escape(cand) + r"(?=[/\s\"'`:;\)\],]|$)", re.IGNORECASE)
            replaced_text, count = pattern.subn(cls.WORKSPACE_PLACEHOLDER, replaced_text)
            total_count += count

        # Also support matching native backslash on Windows if originally present
        if "\\" in source_str:
            escaped_bs = re.escape(source_str)
            pattern_bs = re.compile(escaped_bs + r"(?=[\\\s\"'`:;\)\],]|$)", re.IGNORECASE)
            replaced_text, count2 = pattern_bs.subn(cls.WORKSPACE_PLACEHOLDER, replaced_text)
            total_count += count2

        return replaced_text, total_count

    @classmethod
    def rebind_text(
        cls,
        text: str,
        source_root: Path | str,
        target_root: Path | str,
    ) -> tuple[str, int]:
        """Remap portable placeholders and old host paths to target host's workspace root.

        Args:
            text: Text content to remap.
            source_root: Source workspace root recorded in package manifest.
            target_root: Target workspace root on current receiving host.

        Returns:
            Tuple of (re-bound text, substitution count).
        """
        if not text:
            return "", 0

        target_str = str(Path(target_root).resolve()).replace("\\", "/")
        total_replacements = 0

        # 1. First remap any portable placeholders: ${MYRM_WORKSPACE} -> target_root
        if cls.WORKSPACE_PLACEHOLDER in text:
            text, count_placeholder = re.subn(
                re.escape(cls.WORKSPACE_PLACEHOLDER),
                target_str,
                text,
            )
            total_replacements += count_placeholder

        # 2. Also remap any residual explicit references to the source root
        source_str = str(Path(source_root).resolve()).replace("\\", "/")
        candidate_sources: list[str] = [source_str]
        if source_str.startswith("/private/var/"):
            candidate_sources.append(source_str[len("/private") :])
        elif source_str.startswith("/var/"):
            candidate_sources.append("/private" + source_str)

        for cand in candidate_sources:
            if cand and cand != target_str:
                pattern = re.compile(re.escape(cand) + r"(?=[/\s\"'`:;\)\],]|$)", re.IGNORECASE)
                text, count_direct = pattern.subn(target_str, text.replace("\\", "/"))
                total_replacements += count_direct

        return text, total_replacements

    @classmethod
    def remap_file(
        cls,
        file_path: Path,
        source_root: Path | str,
        target_root: Path | str,
    ) -> int:
        """In-place read, remap, and overwrite a text file with updated workspace paths.

        Returns:
            Number of path replacements made.
        """
        if not file_path.exists() or not file_path.is_file():
            return 0

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Skip binary files safely
            return 0

        remapped_content, count = cls.rebind_text(
            text=content,
            source_root=source_root,
            target_root=target_root,
        )

        if count > 0:
            file_path.write_text(remapped_content, encoding="utf-8")

        return count

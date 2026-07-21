"""Wiki file system structure management.

[INPUT]
pathlib::Path (POS: standard library file path operations)
core.security.path_security::safe_join_path (POS: secure path resolution against traversal)

[OUTPUT]
WikiStructure: LLM-Wiki file system structure manager

[POS]
Wiki file system abstraction layer. Manages Karpathy architecture standard directory layout
(raw/, wiki/, concepts/, index/), providing path generation, file listing, filename sanitization,
and other file system operations.
"""

import re
from pathlib import Path

from myrm_agent_harness.core.security.path_security import safe_join_path


class WikiStructure:
    """
    LLM-Wiki file system structure manager.

    Manages the standard directory layout for Karpathy-style LLM wikis:
    - raw/: Original documents (PDFs, markdown, web clips)
    - wiki/: Compiled wiki articles
    - index/: Index files and catalogs
    - concepts/: Concept articles
    """

    def __init__(self, base_dir: Path | str, public_dirs: list[Path | str] | None = None):
        """
        Initialize wiki structure.

        Args:
            base_dir: Base directory for the wiki.
                      For multi-tenant: /wikis/{tenant_id}/
                      For single-user: /wiki/ or ~/.myrm/wiki/
            public_dirs: Optional list of public enterprise read-only mounted wikis.
        """
        self.base_dir = Path(base_dir)
        self.public_dirs = [Path(p) for p in public_dirs] if public_dirs else []
        self.raw_dir = self.base_dir / "raw"
        self.wiki_dir = self.base_dir / "wiki"
        self.index_dir = self.wiki_dir / "index"
        self.concepts_dir = self.wiki_dir / "concepts"

    def ensure_structure(self) -> None:
        """Create all required directories if they don't exist."""
        for directory in [
            self.base_dir,
            self.raw_dir,
            self.wiki_dir,
            self.index_dir,
            self.concepts_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)

    def get_raw_file_path(self, filename: str) -> Path:
        """Get path for a raw document, with boundary validation against traversal."""
        return safe_join_path(self.raw_dir, filename)

    def get_concept_file_path(self, concept_path: str) -> Path:
        """Get path for a concept article in the local writable directory. Supports nested paths."""
        safe_path = self._sanitize_path(concept_path)
        path = self.concepts_dir / f"{safe_path}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def resolve_concept_file_path(self, concept_path: str) -> Path | None:
        """Resolve path for reading, checking public enterprise mounts if not found locally."""
        local_path = self.get_concept_file_path(concept_path)
        if local_path.exists():
            return local_path

        safe_path = self._sanitize_path(concept_path)
        for p_dir in self.public_dirs:
            public_path = p_dir / "wiki" / "concepts" / f"{safe_path}.md"
            if public_path.exists():
                return public_path
        return None

    def get_index_file_path(self, index_name: str = "main") -> Path:
        """Get path for an index file."""
        return self.index_dir / f"{index_name}.md"

    def list_raw_files(self, pattern: str = "*.md") -> list[Path]:
        """List all raw documents matching the pattern from local sandbox (recursive)."""
        files = sorted(self.raw_dir.rglob(pattern))
        return files

    def list_concepts(self) -> list[Path]:
        """List all concept articles, including from public federated mounts."""
        concepts = sorted(self.concepts_dir.rglob("*.md"))
        for p_dir in self.public_dirs:
            p_concepts = p_dir / "wiki" / "concepts"
            if p_concepts.exists():
                concepts.extend(sorted(p_concepts.rglob("*.md")))
        return concepts

    def get_purpose_path(self) -> Path:
        """Get path for purpose.md (knowledge base direction/scope)."""
        return self.wiki_dir / "purpose.md"

    async def delete_folder_safe(self, folder_path: str, indexer: "WikiIndexer") -> int:
        """
        Safely delete a folder and clear all its files from the indexer to prevent ghost data.

        Args:
            folder_path: The relative path of the folder to delete.
            indexer: The WikiIndexer instance to delete from.

        Returns:
            Number of files deleted and unindexed.
        """
        import shutil

        safe_path = self._sanitize_path(folder_path)
        target_dir = self.concepts_dir / safe_path

        if not target_dir.exists() or not target_dir.is_dir():
            raise FileNotFoundError(f"Directory not found: {safe_path}")

        deleted_count = 0

        # 1. Recursively find all markdown files and delete them from indexer
        for md_file in target_dir.rglob("*.md"):
            try:
                # Calculate the concept name (relative path without extension)
                rel_path = md_file.relative_to(self.concepts_dir)
                concept_name = str(rel_path.with_suffix("")).replace("\\", "/")

                # Delete from indexer
                await indexer.delete(concept_name)
                deleted_count += 1
            except Exception as e:
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to unindex {md_file} before deletion: {e}")

        # 2. Delete the physical directory
        shutil.rmtree(target_dir)

        return deleted_count

    _IGNORED_DIRS: set[str] = {
        ".git", ".svn", ".hg", "node_modules", "__pycache__",
        ".venv", ".env", "__MACOSX", ".obsidian", ".idea", ".vscode",
    }

    def scan_folder(
        self,
        folder_path: Path | str,
        extensions: list[str] | None = None,
    ) -> list[Path]:
        """
        Recursively scan an external folder for importable text documents.
        Automatically skips hidden directories and common non-content directories.

        Args:
            folder_path: Absolute path to the folder to scan.
            extensions: File extensions to include (e.g. ['.md', '.txt', '.org']).
                        Defaults to ['.md', '.txt', '.org'].

        Returns:
            Sorted list of matching file paths.
        """
        target = Path(folder_path)
        if not target.is_dir():
            raise FileNotFoundError(f"Directory not found: {folder_path}")

        if extensions is None:
            extensions = [".md", ".txt", ".org"]

        ext_set = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions}

        files: list[Path] = []
        for f in target.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in ext_set:
                continue
            parts = f.relative_to(target).parts
            if any(p.startswith(".") or p in self._IGNORED_DIRS for p in parts[:-1]):
                continue
            files.append(f)
        return sorted(files)

    def get_wiki_metadata_path(self) -> Path:
        """Get path for wiki metadata (last compile time, stats, etc)."""
        return self.wiki_dir / ".metadata.json"

    @staticmethod
    def _sanitize_path(path_str: str) -> str:
        """
        Sanitize concept path for safe filesystem usage while preserving directory structure.
        Example: "Work/Memory System (Core)" -> "work/memory-system-core"
        """
        parts = []
        for part in path_str.replace("\\", "/").split("/"):
            if not part:
                continue
            # Lowercase, replace spaces and special chars with dashes
            safe = re.sub(r"[^\w\s-]", "", part.lower())
            safe = re.sub(r"[\s_]+", "-", safe)
            safe = safe.strip("-")
            if safe:
                parts.append(safe)
        return "/".join(parts)

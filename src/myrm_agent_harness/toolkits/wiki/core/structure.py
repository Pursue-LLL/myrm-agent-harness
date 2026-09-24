"""Wiki file system structure management.

[INPUT]
- pathlib::Path (POS: standard library file path operations)
- core.security.path_security::safe_join_path (POS: secure path resolution against traversal)
- utils.markdown_frontmatter::parse_frontmatter (POS: robust frontmatter YAML parser)

[OUTPUT]
- WikiStructure: LLM-Wiki file system structure manager

[POS]
Wiki file system abstraction layer. Manages Karpathy architecture standard directory layout
(raw/, wiki/, concepts/, index/), providing path generation, file listing, filename sanitization,
and other file system operations.
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from myrm_agent_harness.core.security.path_security import safe_join_path

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


class WikiStructure:
    """
    LLM-Wiki file system structure manager.

    Manages the standard directory layout for Karpathy-style LLM wikis:
    - raw/: Original documents (PDFs, markdown, web clips)
    - wiki/: Compiled wiki articles and OKF cognitive map (index.md, log.md, hot.md)
    - concepts/: Concept articles
    """

    DIRECTORY_ABSTRACT_FILENAME = ".abstract.md"
    DIRECTORY_OVERVIEW_FILENAME = ".overview.md"
    INDEX_CATALOG_RELATIVE_PATH = "wiki/index.md"
    _vault_alias_shared_cache: ClassVar[dict[str, tuple[float, dict[str, Path]]]] = {}

    def __init__(
        self,
        base_dir: Path | str,
        public_dirs: list[Path | str] | None = None,
        public_dir_labels: dict[str, str] | None = None,
    ):
        """
        Initialize wiki structure.

        Args:
            base_dir: Base directory for the wiki.
                      For multi-tenant: /wikis/{tenant_id}/
                      For single-user: /wiki/ or ~/.myrm/wiki/
            public_dirs: Optional list of public enterprise read-only mounted wikis.
            public_dir_labels: Optional mapping of public dir path or name to display label.
        """
        self.base_dir = Path(base_dir)
        self.public_dirs = [Path(p) for p in public_dirs] if public_dirs else []
        self.public_dir_labels = public_dir_labels or {}
        self.raw_dir = self.base_dir / "raw"
        self.sources_dir = self.base_dir / "sources"
        self.wiki_dir = self.base_dir / "wiki"
        self.concepts_dir = self.wiki_dir / "concepts"
        self.claims_dir = self.concepts_dir / "claims"
        self.methods_dir = self.concepts_dir / "methods"
        self.templates_dir = self.concepts_dir / "templates"
        self.deliverables_dir = self.base_dir / "deliverables"
        self.inbox_dir = self.base_dir / "inbox"
        self.archive_dir = self.wiki_dir / "archive" / "concepts"
        self._alias_to_path_cache: dict[str, Path] | None = None

    def ensure_structure(self) -> None:
        """Create all required directories if they don't exist."""
        for directory in [
            self.base_dir,
            self.raw_dir,
            self.sources_dir,
            self.wiki_dir,
            self.concepts_dir,
            self.claims_dir,
            self.methods_dir,
            self.templates_dir,
            self.deliverables_dir,
            self.inbox_dir,
            self.archive_dir,
            self.wiki_dir / "assets",
        ]:
            directory.mkdir(parents=True, exist_ok=True)

    def get_raw_file_path(self, filename: str) -> Path:
        """Get path for a raw document, with boundary validation against traversal."""
        return safe_join_path(self.raw_dir, filename)

    def get_source_file_path(self, source_id: str) -> Path:
        """Get path for a structured source identity card (sources/<source_id>.md)."""
        safe_name = self._sanitize_path(source_id)
        path = self.sources_dir / f"{safe_name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_deliverable_file_path(self, filename: str) -> Path:
        """Get path for a task deliverable (deliverables/<filename>)."""
        return safe_join_path(self.deliverables_dir, filename)

    def get_inbox_file_path(self, filename: str) -> Path:
        """Get path for an external radar ingested item in inbox/."""
        return safe_join_path(self.inbox_dir, filename)

    def get_claim_file_path(self, claim_path: str) -> Path:
        """Get path for a subjective author claim page."""
        safe_path = self._sanitize_path(claim_path)
        path = self.claims_dir / f"{safe_path}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_method_file_path(self, method_path: str) -> Path:
        """Get path for an operational methodology page."""
        safe_path = self._sanitize_path(method_path)
        path = self.methods_dir / f"{safe_path}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_template_file_path(self, template_path: str) -> Path:
        """Get path for a reusable work template page."""
        safe_path = self._sanitize_path(template_path)
        path = self.templates_dir / f"{safe_path}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_concept_file_path(self, concept_path: str) -> Path:
        """Get path for a concept article in the local writable directory. Supports nested paths."""
        safe_path = self._sanitize_path(concept_path)
        path = self.concepts_dir / f"{safe_path}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_archived_concept_file_path(self, concept_path: str) -> Path:
        """Get path for an archived concept article in the isolated archive directory."""
        safe_path = self._sanitize_path(concept_path)
        path = self.archive_dir / f"{safe_path}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_directory_sidecar_paths(
        self,
        concept_dir: str,
        *,
        create: bool = True,
    ) -> tuple[Path, Path]:
        """Get directory sidecar paths (L0 abstract + L1 overview) for a concept directory."""
        safe_dir = self._sanitize_path(concept_dir)
        base_dir = self.concepts_dir if not safe_dir else self.concepts_dir / safe_dir
        if create:
            base_dir.mkdir(parents=True, exist_ok=True)
        return (
            base_dir / self.DIRECTORY_ABSTRACT_FILENAME,
            base_dir / self.DIRECTORY_OVERVIEW_FILENAME,
        )

    def resolve_concept_file_path(self, concept_path: str) -> Path | None:
        """Resolve path for reading, checking public enterprise mounts if not found locally."""
        clean_path = concept_path
        if clean_path.startswith("wiki/"):
            clean_path = clean_path[len("wiki/") :]
        if clean_path.startswith("concepts/"):
            clean_path = clean_path[len("concepts/") :]
        if clean_path.endswith(".md"):
            clean_path = clean_path[:-3]

        safe_path = self._sanitize_path(clean_path)
        local_path = self.concepts_dir / f"{safe_path}.md"
        if local_path.is_file():
            return local_path
        direct_local = self.concepts_dir / f"{clean_path}.md"
        if direct_local.is_file():
            return direct_local

        for p_dir in self.public_dirs[:6]:
            try:
                public_path = p_dir / "wiki" / "concepts" / f"{safe_path}.md"
                if public_path.is_file():
                    return public_path
                direct_pub_concepts = p_dir / "wiki" / "concepts" / f"{clean_path}.md"
                if direct_pub_concepts.is_file():
                    return direct_pub_concepts
                direct_path = p_dir / concept_path
                if direct_path.is_file():
                    return direct_path
            except (OSError, PermissionError):
                continue
        alias_path = self.resolve_alias_file_path(clean_path)
        if alias_path is not None and alias_path.is_file():
            return alias_path
        return None

    def resolve_alias_file_path(self, alias_name: str) -> Path | None:
        """Resolve a concept file path by frontmatter alias.

        Reads cached alias-to-path index, or builds it on demand by scanning concept articles.
        """
        if not alias_name:
            return None
        clean_key = alias_name.removesuffix(".md").strip().lower()
        if self._alias_to_path_cache is None:
            self._rebuild_alias_cache()
        if self._alias_to_path_cache:
            return self._alias_to_path_cache.get(clean_key)
        return None

    def invalidate_alias_cache(self) -> None:
        """Clear memory cache of frontmatter alias index."""
        self._alias_to_path_cache = None
        try:
            cache_key = str(self.concepts_dir.resolve())
            self._vault_alias_shared_cache.pop(cache_key, None)
        except Exception:
            pass

    def _rebuild_alias_cache(self) -> None:
        """Scan active concepts to build alias -> Path mapping, with mtime-guarded process cache."""
        dir_mtime = 0.0
        cache_key = ""
        try:
            if self.concepts_dir.is_dir():
                cache_key = str(self.concepts_dir.resolve())
                dir_mtime = self.concepts_dir.stat().st_mtime
                if cache_key in self._vault_alias_shared_cache:
                    cached_mtime, cached_mapping = self._vault_alias_shared_cache[cache_key]
                    if cached_mtime == dir_mtime:
                        self._alias_to_path_cache = cached_mapping.copy()
                        return
        except Exception:
            pass

        mapping: dict[str, Path] = {}
        for concept_path in self.list_concepts():
            try:
                with open(concept_path, encoding="utf-8", errors="ignore") as f:
                    chunk = f.read(2048)
                from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

                fm, _ = parse_frontmatter(chunk)
                aliases = fm.get("aliases")
                if isinstance(aliases, list):
                    for a in aliases:
                        if isinstance(a, str) and a.strip():
                            mapping[a.strip().lower()] = concept_path
                elif isinstance(aliases, str) and aliases.strip():
                    for a in aliases.split(","):
                        if a.strip():
                            mapping[a.strip().lower()] = concept_path
            except (OSError, UnicodeDecodeError):
                continue
        self._alias_to_path_cache = mapping
        if cache_key:
            self._vault_alias_shared_cache[cache_key] = (dir_mtime, mapping)

    def get_index_file_path(self) -> Path:
        """Get path for the OKF root index catalog (wiki/index.md)."""
        return self.wiki_dir / "index.md"

    def get_index_catalog_relative_path(self) -> str:
        """Vault-relative path for wiki/index.md citations."""
        return self.INDEX_CATALOG_RELATIVE_PATH

    def get_log_file_path(self) -> Path:
        """Get path for the human-readable activity log (wiki/log.md)."""
        return self.wiki_dir / "log.md"

    def get_hot_file_path(self) -> Path:
        """Get path for the session hot cache (wiki/hot.md)."""
        return self.wiki_dir / "hot.md"

    def get_schema_file_path(self) -> Path:
        """Get path for the human-readable vault schema contract (wiki/SCHEMA.md)."""
        return self.wiki_dir / "SCHEMA.md"

    def list_raw_files(self, pattern: str = "*.md") -> list[Path]:
        """List all raw documents matching the pattern from local sandbox (recursive)."""
        files = sorted(self.raw_dir.rglob(pattern))
        return files

    def list_concepts(self) -> list[Path]:
        """List all concept articles, including from public federated mounts (max 6)."""
        concepts = [p for p in sorted(self.concepts_dir.rglob("*.md")) if not self._is_directory_sidecar(p)]
        for p_dir in self.public_dirs[:6]:
            try:
                p_concepts = p_dir / "wiki" / "concepts"
                if p_concepts.is_dir():
                    concepts.extend(p for p in sorted(p_concepts.rglob("*.md")) if not self._is_directory_sidecar(p))
            except (OSError, PermissionError):
                continue
        return concepts

    def list_archived_concepts(self) -> list[Path]:
        """List all archived concept articles from local isolated archive directory."""
        if not self.archive_dir.exists():
            return []
        return [p for p in sorted(self.archive_dir.rglob("*.md")) if not self._is_directory_sidecar(p)]

    async def archive_concept_safe(
        self,
        concept_name: str,
        indexer: "WikiIndexer | None" = None,
        reason: str = "",
    ) -> Path:
        """Atomically archive a concept article out of active concepts and unindex from FTS5."""
        source_path = self.get_concept_file_path(concept_name)
        if not source_path.exists():
            raise FileNotFoundError(f"Active concept not found: {concept_name}")

        target_path = self.get_archived_concept_file_path(concept_name)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Unindex from FTS5 & vector if indexer provided
        if indexer is not None:
            try:
                await indexer.delete(concept_name)
            except Exception as exc:
                import logging

                logging.getLogger(__name__).warning(
                    "Failed to unindex concept %s before archive: %s", concept_name, exc
                )

        # 2. Atomic file move
        source_path.replace(target_path)
        self.invalidate_alias_cache()
        return target_path

    async def revive_concept_safe(
        self,
        concept_name: str,
        indexer: "WikiIndexer | None" = None,
    ) -> Path:
        """Atomically revive an archived concept back to active concepts directory."""
        archive_path = self.get_archived_concept_file_path(concept_name)
        if not archive_path.exists():
            raise FileNotFoundError(f"Archived concept not found: {concept_name}")

        target_path = self.get_concept_file_path(concept_name)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Atomic file move
        archive_path.replace(target_path)
        self.invalidate_alias_cache()

        # 2. Reindex if indexer provided
        if indexer is not None:
            try:
                await indexer.index_file(target_path)
            except Exception as exc:
                import logging

                logging.getLogger(__name__).warning("Failed to reindex revived concept %s: %s", concept_name, exc)

        return target_path

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
            if self._is_directory_sidecar(md_file):
                continue
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

    _IGNORED_DIRS: ClassVar[set[str]] = {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "__pycache__",
        ".venv",
        ".env",
        "__MACOSX",
        ".obsidian",
        ".idea",
        ".vscode",
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
        ignore_patterns = self.load_wikiignore_patterns()
        for f in target.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in ext_set:
                continue
            parts = f.relative_to(target).parts
            if any(p.startswith(".") or p in self._IGNORED_DIRS for p in parts[:-1]):
                continue
            rel_posix = f.relative_to(target).as_posix()
            if self.path_matches_wikiignore(rel_posix, ignore_patterns):
                continue
            files.append(f)
        return sorted(files)

    def load_wikiignore_patterns(self) -> tuple[str, ...]:
        from myrm_agent_harness.toolkits.wiki.pipeline.ingress.wikiignore import (
            load_wikiignore_patterns,
        )

        return load_wikiignore_patterns(self)

    @staticmethod
    def path_matches_wikiignore(
        relative_posix: str,
        patterns: tuple[str, ...],
    ) -> bool:
        from myrm_agent_harness.toolkits.wiki.pipeline.ingress.wikiignore import (
            path_matches_wikiignore,
        )

        return path_matches_wikiignore(relative_posix, patterns)

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

    @classmethod
    def _is_directory_sidecar(cls, path: Path) -> bool:
        return path.name in {
            cls.DIRECTORY_ABSTRACT_FILENAME,
            cls.DIRECTORY_OVERVIEW_FILENAME,
        }

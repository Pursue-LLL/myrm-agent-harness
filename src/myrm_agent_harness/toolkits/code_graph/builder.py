"""Code graph builder — full and incremental builds with streaming memory safety.

Coordinates Tree-sitter parsing across files and populates the CodeGraphStore.
Supports full workspace builds and git-diff-based incremental updates with
file hashing to skip unchanged files.

[INPUT]
- CodeGraphStore (POS: opened graph store)
- Path (POS: workspace root directory)

[OUTPUT]
- CodeGraphBuilder: orchestrates full/incremental graph construction
- BuildResult: summary statistics from a build operation

[POS]
Graph construction pipeline for workspace-scale AST analysis. Processes files
in bounded batches to prevent memory spikes on large repositories.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.code_graph.parser import (
    SUPPORTED_LANGUAGES,
    parse_file,
)
from myrm_agent_harness.toolkits.code_graph.store import CodeGraphStore

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_graph.parser._base import ParseResult

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
MAX_FILE_SIZE = 1024 * 1024
PARSE_WORKERS = min(4, (os.cpu_count() or 1))

_DEFAULT_IGNORE_DIRS = frozenset({
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache",
    "venv", ".venv", "env", ".env",
    "dist", "build", "target", "out",
    ".next", ".nuxt", ".output",
    "vendor", "third_party",
})


@dataclass(slots=True)
class BuildResult:
    """Summary of a graph build operation."""

    files_processed: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    nodes_added: int = 0
    edges_added: int = 0
    elapsed_seconds: float = 0.0
    is_incremental: bool = False


class CodeGraphBuilder:
    """Orchestrates full and incremental code graph construction."""

    def __init__(
        self,
        store: CodeGraphStore,
        workspace_root: Path,
        *,
        ignore_dirs: frozenset[str] | None = None,
        max_file_size: int = MAX_FILE_SIZE,
    ) -> None:
        self._store = store
        self._workspace = workspace_root
        self._ignore_dirs = ignore_dirs or _DEFAULT_IGNORE_DIRS
        self._max_file_size = max_file_size

    def build_full(self) -> BuildResult:
        """Full workspace scan: parse all supported files."""
        start = time.monotonic()
        result = BuildResult(is_incremental=False)

        self._store.clear()

        files = self._discover_files()
        for batch in _chunked(files, BATCH_SIZE):
            self._process_batch(batch, result)

        result.elapsed_seconds = time.monotonic() - start
        logger.info(
            "Full build: %d files processed, %d skipped, %d nodes, %d edges (%.1fs)",
            result.files_processed, result.files_skipped,
            result.nodes_added, result.edges_added, result.elapsed_seconds,
        )
        return result

    def build_incremental(self, changed_files: list[str] | None = None) -> BuildResult:
        """Incremental build: only re-parse changed files.

        If changed_files is None, uses git diff to detect changes.
        """
        start = time.monotonic()
        result = BuildResult(is_incremental=True)

        if changed_files is None:
            changed_files = self._detect_git_changes()

        supported = [f for f in changed_files if self._is_supported(f)]

        deleted = [f for f in supported if not (self._workspace / f).exists()]
        for f in deleted:
            self._store.remove_file(f)
            result.files_skipped += 1

        existing = [f for f in supported if f not in deleted]
        for batch in _chunked(existing, BATCH_SIZE):
            self._process_batch(batch, result, incremental=True)

        result.elapsed_seconds = time.monotonic() - start
        logger.info(
            "Incremental build: %d files processed, %d skipped, %d nodes, %d edges (%.1fs)",
            result.files_processed, result.files_skipped,
            result.nodes_added, result.edges_added, result.elapsed_seconds,
        )
        return result

    def _discover_files(self) -> list[str]:
        files: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self._workspace):
            dirnames[:] = [
                d for d in dirnames
                if d not in self._ignore_dirs and not d.startswith(".")
            ]
            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                relpath = os.path.relpath(fpath, self._workspace)
                if self._is_supported(relpath) and self._check_size(fpath):
                    files.append(relpath)
        return files

    def _detect_git_changes(self) -> list[str]:
        try:
            output = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=self._workspace,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if output.returncode == 0 and output.stdout.strip():
                return output.stdout.strip().split("\n")

            output = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                cwd=self._workspace,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if output.returncode == 0 and output.stdout.strip():
                return output.stdout.strip().split("\n")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return self._discover_files()

    def _process_batch(
        self,
        files: list[str],
        result: BuildResult,
        *,
        incremental: bool = False,
    ) -> None:
        to_parse: list[tuple[str, str, str]] = []
        for rel_path in files:
            abs_path = self._workspace / rel_path
            try:
                source = abs_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                result.files_failed += 1
                continue

            file_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]

            if incremental:
                stored_hash = self._store.get_file_hash(rel_path)
                if stored_hash == file_hash:
                    result.files_skipped += 1
                    continue
                self._store.remove_file(rel_path)

            to_parse.append((rel_path, source, file_hash))

        parsed = self._parse_parallel(to_parse)

        for rel_path, file_hash, parse_result in parsed:
            if parse_result is None:
                result.files_skipped += 1
                continue
            if parse_result.errors:
                logger.debug("Parse errors in %s: %s", rel_path, parse_result.errors)
                result.files_failed += 1
                continue
            if parse_result.nodes:
                count = self._store.upsert_nodes(parse_result.nodes, file_hash=file_hash)
                result.nodes_added += count
            if parse_result.edges:
                count = self._store.upsert_edges(parse_result.edges)
                result.edges_added += count
            result.files_processed += 1

    @staticmethod
    def _parse_one(item: tuple[str, str, str]) -> tuple[str, str, ParseResult | None]:
        rel_path, source, file_hash = item
        return (rel_path, file_hash, parse_file(rel_path, source))

    def _parse_parallel(
        self,
        items: list[tuple[str, str, str]],
    ) -> list[tuple[str, str, ParseResult | None]]:
        if len(items) <= 2:
            return [self._parse_one(item) for item in items]
        results: list[tuple[str, str, ParseResult | None]] = []
        with ThreadPoolExecutor(max_workers=PARSE_WORKERS) as executor:
            futures = {executor.submit(self._parse_one, item): item for item in items}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception:
                    rel_path = futures[future][0]
                    logger.warning("Parse worker failed for %s", rel_path, exc_info=True)
                    results.append((rel_path, futures[future][2], None))
        return results

    def _is_supported(self, rel_path: str) -> bool:
        ext = Path(rel_path).suffix.lower()
        return ext in SUPPORTED_LANGUAGES

    def _check_size(self, abs_path: str) -> bool:
        try:
            return os.path.getsize(abs_path) <= self._max_file_size
        except OSError:
            return False


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]

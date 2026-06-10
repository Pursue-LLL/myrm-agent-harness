"""Workspace Code Indexer — FTS5 + optional Vector hybrid search for source code.

[INPUT]
sqlite3 (POS: standard library database)
pathlib::Path (POS: standard library path)
.config::CodeIndexConfig (POS: indexing configuration)
.symbol_extractor::extract_symbols, detect_language, CodeSymbol (POS: regex symbol extraction)
myrm_agent_harness.toolkits.retriever.fusion_strategies::rrf_fusion (POS: result fusion)
myrm_agent_harness.toolkits.vector.base::VectorDocument (POS: vector document model)

[OUTPUT]
CodeIndexer: On-demand workspace code indexer with FTS5+Vector hybrid search

[POS]
Lightweight on-demand code indexer. Reuses the project's existing FTS5, embedding,
and vector infrastructure to provide semantic code search without a background daemon.
Indexes lazily via mtime comparison, persists to {workspace}/.myrm/code_index.db.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.retriever.fusion_strategies import rrf_fusion
from myrm_agent_harness.toolkits.vector.base import VectorDocument

from .config import CodeIndexConfig
from .symbol_extractor import CodeSymbol, detect_language, extract_symbols

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uF900-\uFAFF]+")


def _tokenize_for_fts(query: str) -> str:
    """Build FTS5 query with CJK bigram support."""
    tokens: list[str] = []

    cjk_segments = _CJK_RE.findall(query)
    for seg in cjk_segments:
        if len(seg) == 1:
            tokens.append(f'"{seg}"')
        else:
            for i in range(len(seg) - 1):
                tokens.append(f'"{seg[i]}{seg[i + 1]}"')

    latin_text = _CJK_RE.sub(" ", query)
    for word in latin_text.split():
        cleaned = word.strip().strip('"').strip("'")
        if cleaned and len(cleaned) >= 2:
            tokens.append(f'"{cleaned}"')

    return " ".join(tokens)


class CodeIndexer:
    """On-demand workspace code indexer with FTS5 + Vector hybrid search.

    Indexes source code files in a workspace directory, extracting symbols
    (functions, classes, methods) and file-level content summaries. Uses
    mtime-based incremental updates — no background daemon needed.

    Usage:
        indexer = CodeIndexer(Path("/workspace"), config)
        await indexer.ensure_indexed()
        results = await indexer.search("authentication handler")
    """

    def __init__(
        self,
        workspace_dir: Path,
        config: CodeIndexConfig | None = None,
        vector_store: VectorStoreProtocol | None = None,
        embedding: EmbeddingProtocol | None = None,
    ) -> None:
        self._workspace = workspace_dir.resolve()
        self._config = config or CodeIndexConfig()
        self._vector = vector_store
        self._embedding = embedding
        self._collection_ready = False

        self._myrm_dir = self._workspace / ".myrm"
        self._myrm_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._myrm_dir / self._config.index_db_name

        self._indexed = False
        self._init_db()

    @contextlib.contextmanager
    def _get_conn(self):
        """Get a hardened SQLite connection with WAL mode."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            from myrm_agent_harness.utils.db.sqlite import CACHE, harden_connection_sync
            harden_connection_sync(conn, CACHE, db_path=self._db_path)
        except ImportError:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create database tables if they don't exist."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS code_files (
                    file_path TEXT PRIMARY KEY,
                    mtime_ns INTEGER NOT NULL,
                    file_size INTEGER NOT NULL,
                    language TEXT,
                    indexed_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS code_fts USING fts5(
                    file_path,
                    symbols,
                    content_summary,
                    tokenize="unicode61 remove_diacritics 1"
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS code_symbols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    line INTEGER NOT NULL,
                    signature TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    FOREIGN KEY (file_path) REFERENCES code_files(file_path) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_symbols_name ON code_symbols(name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_symbols_file ON code_symbols(file_path)
            """)

    async def ensure_indexed(self) -> dict[str, int]:
        """Ensure the workspace is indexed. Returns stats dict.

        Performs incremental indexing: only re-indexes files whose mtime
        has changed since last index. Thread-safe via SQLite WAL.

        Returns:
            Dict with keys: total_files, new_files, updated_files, removed_files
        """
        stats = {"total_files": 0, "new_files": 0, "updated_files": 0, "removed_files": 0}

        current_files = await asyncio.to_thread(self._scan_workspace_files)
        stats["total_files"] = len(current_files)

        with self._get_conn() as conn:
            indexed_files = {
                row["file_path"]: row["mtime_ns"]
                for row in conn.execute("SELECT file_path, mtime_ns FROM code_files").fetchall()
            }

        files_to_index: list[tuple[str, int, int]] = []
        files_to_remove: list[str] = []
        current_paths = set()

        for rel_path, mtime_ns, file_size in current_files:
            current_paths.add(rel_path)
            if rel_path not in indexed_files:
                files_to_index.append((rel_path, mtime_ns, file_size))
                stats["new_files"] += 1
            elif indexed_files[rel_path] != mtime_ns:
                files_to_index.append((rel_path, mtime_ns, file_size))
                stats["updated_files"] += 1

        for indexed_path in indexed_files:
            if indexed_path not in current_paths:
                files_to_remove.append(indexed_path)
                stats["removed_files"] += 1

        if files_to_remove:
            await asyncio.to_thread(self._remove_files, files_to_remove)

        if files_to_index:
            batch_size = self._config.batch_size
            for i in range(0, len(files_to_index), batch_size):
                batch = files_to_index[i:i + batch_size]
                await self._index_batch(batch)

        self._indexed = True
        logger.info(
            "Code index updated: %d total, %d new, %d updated, %d removed",
            stats["total_files"], stats["new_files"],
            stats["updated_files"], stats["removed_files"],
        )
        return stats

    def _scan_workspace_files(self) -> list[tuple[str, int, int]]:
        """Scan workspace for indexable source files. Returns (rel_path, mtime_ns, size)."""
        results: list[tuple[str, int, int]] = []
        exclude_dirs = self._config.exclude_dirs
        binary_exts = self._config.binary_extensions
        max_size = self._config.max_file_size_bytes
        max_files = self._config.max_files

        for dirpath, dirnames, filenames in os.walk(self._workspace, topdown=True):
            dirnames[:] = [
                d for d in dirnames
                if d not in exclude_dirs and not d.startswith(".")
            ]

            for fname in filenames:
                if len(results) >= max_files:
                    return results

                fpath = Path(dirpath) / fname
                ext = fpath.suffix.lower()
                if ext in binary_exts or not ext:
                    continue

                if not detect_language(fpath):
                    continue

                try:
                    stat = fpath.stat()
                    if stat.st_size > max_size or stat.st_size == 0:
                        continue
                    rel = str(fpath.relative_to(self._workspace))
                    results.append((rel, stat.st_mtime_ns, stat.st_size))
                except (OSError, ValueError):
                    continue

        return results

    async def _index_batch(self, batch: list[tuple[str, int, int]]) -> None:
        """Index a batch of files."""
        entries: list[tuple[str, int, int, str, str | None, list[CodeSymbol]]] = []

        for rel_path, mtime_ns, file_size in batch:
            abs_path = self._workspace / rel_path
            try:
                content = await asyncio.to_thread(abs_path.read_text, "utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            lang = detect_language(rel_path)
            symbols = extract_symbols(content, rel_path, lang)
            summary = _build_content_summary(content, symbols, max_chars=500)
            entries.append((rel_path, mtime_ns, file_size, summary, lang, symbols))

        def _write_batch():
            with self._get_conn() as conn:
                for rel_path, mtime_ns, file_size, summary, lang, symbols in entries:
                    conn.execute("DELETE FROM code_files WHERE file_path = ?", (rel_path,))
                    conn.execute("DELETE FROM code_fts WHERE file_path = ?", (rel_path,))
                    conn.execute("DELETE FROM code_symbols WHERE file_path = ?", (rel_path,))

                    conn.execute(
                        "INSERT INTO code_files (file_path, mtime_ns, file_size, language, indexed_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (rel_path, mtime_ns, file_size, lang, time.time()),
                    )

                    symbol_names = " ".join(s.name for s in symbols)
                    conn.execute(
                        "INSERT INTO code_fts (file_path, symbols, content_summary) VALUES (?, ?, ?)",
                        (rel_path, symbol_names, summary),
                    )

                    for sym in symbols:
                        conn.execute(
                            "INSERT INTO code_symbols (name, kind, line, signature, file_path) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (sym.name, sym.kind, sym.line, sym.signature, rel_path),
                        )

        await asyncio.to_thread(_write_batch)

        if self._config.enable_vector_search and self._vector and self._embedding:
            await self._vector_index_batch(entries)

    async def _vector_index_batch(
        self,
        entries: list[tuple[str, int, int, str, str | None, list[CodeSymbol]]],
    ) -> None:
        """Index entries into the vector store for semantic search."""
        await self._ensure_collection()
        if not self._collection_ready:
            return

        docs: list[VectorDocument] = []
        texts: list[str] = []
        for rel_path, _, _, summary, lang, symbols in entries:
            chunk_text = f"File: {rel_path}\n"
            if symbols:
                chunk_text += "Symbols: " + ", ".join(f"{s.kind} {s.name}" for s in symbols[:20]) + "\n"
            chunk_text += summary
            texts.append(chunk_text)

        if not texts:
            return

        try:
            vectors = await self._embedding.embed_batch(texts)
        except Exception as e:
            logger.warning("Failed to embed code chunks: %s", e)
            return

        for idx, (rel_path, _, _, summary, lang, symbols) in enumerate(entries):
            doc_id = _path_to_uuid(rel_path)
            docs.append(VectorDocument(
                id=doc_id,
                content=texts[idx],
                vector=vectors[idx],
                metadata={"file_path": rel_path, "language": lang or "unknown"},
            ))

        try:
            await self._vector.upsert(self._config.collection_name, docs)
        except Exception as e:
            logger.warning("Failed to upsert code vectors: %s", e)

    async def _ensure_collection(self) -> None:
        """Lazily initialize vector collection."""
        if not self._vector or not self._embedding or self._collection_ready:
            return
        try:
            test_vec = await self._embedding.embed("test")
            dim = len(test_vec)
            if hasattr(self._vector, "ensure_collection"):
                await self._vector.ensure_collection(self._config.collection_name, dim)
            self._collection_ready = True
        except Exception as e:
            logger.warning("Failed to ensure code index vector collection: %s", e)

    def _remove_files(self, file_paths: list[str]) -> None:
        """Remove files from the index."""
        with self._get_conn() as conn:
            for fp in file_paths:
                conn.execute("DELETE FROM code_files WHERE file_path = ?", (fp,))
                conn.execute("DELETE FROM code_fts WHERE file_path = ?", (fp,))
                conn.execute("DELETE FROM code_symbols WHERE file_path = ?", (fp,))

    async def search(self, query: str, limit: int | None = None) -> list[dict[str, str | int | float]]:
        """Search indexed code using FTS5 + optional Vector hybrid search.

        Args:
            query: Natural language or keyword search query.
            limit: Max results (defaults to config.max_search_results).

        Returns:
            List of result dicts with keys: file_path, score, symbols, summary, language, line.
        """
        if not query.strip():
            return []

        effective_limit = limit or self._config.max_search_results

        fts_results = await asyncio.to_thread(self._fts_search, query, effective_limit * 2)

        vec_results: list[tuple[str, float]] = []
        if self._config.enable_vector_search and self._vector and self._embedding and self._collection_ready:
            vec_results = await self._vector_search(query, effective_limit * 2)

        if vec_results:
            fused = rrf_fusion([fts_results, vec_results], k=60)
            ranked_paths = fused[:effective_limit]
        else:
            ranked_paths = fts_results[:effective_limit]

        return await asyncio.to_thread(self._build_results, ranked_paths)

    def _fts_search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """FTS5 keyword search."""
        fts_query = _tokenize_for_fts(query)
        if not fts_query:
            return []

        results: list[tuple[str, float]] = []
        with self._get_conn() as conn:
            try:
                cursor = conn.execute(
                    "SELECT file_path, rank FROM code_fts WHERE code_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (fts_query, limit),
                )
                for row in cursor.fetchall():
                    score = 1.0 / (abs(row["rank"]) + 1.0)
                    results.append((row["file_path"], score))
            except sqlite3.OperationalError as e:
                logger.debug("FTS search error: %s", e)
        return results

    async def _vector_search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """Vector semantic search."""
        try:
            query_vec = await self._embedding.embed(query)
            search_res = await self._vector.search(
                self._config.collection_name, query_vector=query_vec, limit=limit,
            )
            return [
                (res.document.metadata.get("file_path", res.document.id), res.score)
                for res in search_res
            ]
        except Exception as e:
            logger.debug("Vector search error: %s", e)
            return []

    def _build_results(self, ranked_paths: list[tuple[str, float]]) -> list[dict[str, str | int | float]]:
        """Build rich result dicts from ranked file paths."""
        results: list[dict[str, str | int | float]] = []
        with self._get_conn() as conn:
            for file_path, score in ranked_paths:
                file_row = conn.execute(
                    "SELECT language FROM code_files WHERE file_path = ?",
                    (file_path,),
                ).fetchone()

                symbols_rows = conn.execute(
                    "SELECT name, kind, line, signature FROM code_symbols "
                    "WHERE file_path = ? ORDER BY line LIMIT 10",
                    (file_path,),
                ).fetchall()

                fts_row = conn.execute(
                    "SELECT content_summary FROM code_fts WHERE file_path = ?",
                    (file_path,),
                ).fetchone()

                result: dict[str, str | int | float] = {
                    "file_path": file_path,
                    "score": round(score, 4),
                    "language": file_row["language"] if file_row else "unknown",
                    "summary": fts_row["content_summary"] if fts_row else "",
                }

                if symbols_rows:
                    result["symbols"] = "; ".join(
                        f"{r['kind']} {r['name']} L{r['line']}" for r in symbols_rows
                    )
                    result["line"] = symbols_rows[0]["line"]

                results.append(result)
        return results

    def get_stats(self) -> dict[str, int | dict[str, int]]:
        """Get index statistics."""
        with self._get_conn() as conn:
            file_count: int = conn.execute("SELECT COUNT(*) FROM code_files").fetchone()[0]
            symbol_count: int = conn.execute("SELECT COUNT(*) FROM code_symbols").fetchone()[0]
            languages = conn.execute(
                "SELECT language, COUNT(*) as cnt FROM code_files GROUP BY language ORDER BY cnt DESC"
            ).fetchall()
        return {
            "indexed_files": file_count,
            "indexed_symbols": symbol_count,
            "languages": {r["language"]: r["cnt"] for r in languages if r["language"]},
        }

    async def search_symbol(self, name: str, kind: str | None = None) -> list[CodeSymbol]:
        """Search for a specific symbol by exact name (Trae CKG compatible).

        Args:
            name: Symbol name to search for.
            kind: Optional kind filter ("function", "class", "method", etc.)
        """
        def _query():
            with self._get_conn() as conn:
                if kind:
                    rows = conn.execute(
                        "SELECT name, kind, line, signature, file_path FROM code_symbols "
                        "WHERE name = ? AND kind = ? ORDER BY file_path",
                        (name, kind),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT name, kind, line, signature, file_path FROM code_symbols "
                        "WHERE name = ? ORDER BY file_path",
                        (name,),
                    ).fetchall()
                return [
                    CodeSymbol(
                        name=r["name"], kind=r["kind"], line=r["line"],
                        signature=r["signature"], file_path=r["file_path"],
                    )
                    for r in rows
                ]
        return await asyncio.to_thread(_query)


def _build_content_summary(content: str, symbols: list[CodeSymbol], max_chars: int = 500) -> str:
    """Build a searchable content summary from file content and extracted symbols."""
    parts: list[str] = []
    lines = content.split("\n")
    for line in lines[:5]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#!"):
            parts.append(stripped)

    if symbols:
        parts.append("Definitions: " + ", ".join(s.name for s in symbols[:15]))

    summary = "\n".join(parts)
    return summary[:max_chars]


def _path_to_uuid(file_path: str) -> str:
    """Convert a file path to a deterministic UUID for vector store."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"code:{file_path}"))

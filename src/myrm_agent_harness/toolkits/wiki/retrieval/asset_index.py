"""Wiki asset indexer — caption-based hybrid search for wiki/assets images.

[INPUT]
..core.structure::WikiStructure (POS: wiki paths)
..core.config::WikiConfig (POS: feature flags)
myrm_agent_harness.toolkits.retriever.fusion_strategies::rrf_fusion (POS: RRF merge)
.tokenizer::tokenize_for_fts (POS: FTS5 query builder)

[OUTPUT]
WikiAssetIndexer: FTS5 + optional Qdrant index for image captions
AssetSearchHit, AssetIndexStats, AssetIndexResult, AssetCaptionProvider
purge_orphan_entries(): remove index rows for deleted on-disk assets

[POS]
Parallel retrieval module for Obsidian-imported images under wiki/assets/.
Index-time vision captioning is injected via AssetCaptionProvider (server wires VisionFallbackEngine).
Search results fuse into WikiQueryEngine; no agent meta-tool registration.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
import sqlite3
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from myrm_agent_harness.toolkits.retriever.fusion_strategies import rrf_fusion
from myrm_agent_harness.utils.db.fts5 import fts5_auto_heal, fts5_integrity_check, fts5_rebuild

from ..core.config import WikiConfig
from ..core.structure import WikiStructure
from .tokenizer import tokenize_for_fts
from .vector_chunks import upsert_text_vectors

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".avif"})
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_COLLECTION_NAME = "wiki_assets"


class AssetCaptionProvider(Protocol):
    async def caption_file(self, path: Path) -> str: ...


@dataclass(frozen=True, slots=True)
class AssetSearchHit:
    filename: str
    caption: str
    score: float
    source_concepts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AssetIndexStats:
    indexed: int
    pending: int
    failed: int
    total_files: int


@dataclass(frozen=True, slots=True)
class AssetIndexResult:
    indexed: int
    skipped: int
    failed: int


class WikiAssetIndexer:
    """Hybrid caption indexer for files under wiki/assets/."""

    def __init__(
        self,
        structure: WikiStructure,
        config: WikiConfig | None = None,
        vector_store: VectorStoreProtocol | None = None,
        embedding: EmbeddingProtocol | None = None,
        caption_provider: AssetCaptionProvider | None = None,
    ) -> None:
        self._structure = structure
        self._config = config or WikiConfig()
        self._vector = vector_store
        self._embedding = embedding
        self._caption_provider = caption_provider
        self.db_path = self._structure.base_dir / ".wiki_index.db"
        self._collection_ready = False
        self._init_db()

    @property
    def assets_dir(self) -> Path:
        return self._structure.wiki_dir / "assets"

    @contextlib.contextmanager
    def _get_conn(self) -> Iterator[sqlite3.Connection]:
        from myrm_agent_harness.utils.db.sqlite import CACHE, harden_connection_sync

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        harden_connection_sync(conn, CACHE, db_path=self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS wiki_assets_fts USING fts5(
                    filename,
                    caption,
                    tokenize="unicode61 remove_diacritics 1"
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS wiki_assets_meta(
                    filename TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    caption TEXT NOT NULL DEFAULT '',
                    source_concepts TEXT NOT NULL DEFAULT '[]',
                    indexed_at TEXT NOT NULL DEFAULT '',
                    index_status TEXT NOT NULL DEFAULT 'pending'
                )
            """)
            if not fts5_integrity_check(conn, "wiki_assets_fts"):
                logger.warning("FTS5 index corrupted on startup, rebuilding: wiki_assets_fts")
                fts5_rebuild(conn, "wiki_assets_fts")

    @staticmethod
    def _asset_to_uuid(filename: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_OID, f"wiki_asset:{filename}"))

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def scan_image_references(self) -> dict[str, list[str]]:
        """Map asset filename -> concept names that embed the image."""
        refs: dict[str, set[str]] = {}
        search_roots = [self._structure.concepts_dir, self._structure.raw_dir]
        for root in search_roots:
            if not root.exists():
                continue
            for md_path in root.rglob("*.md"):
                try:
                    content = md_path.read_text(encoding="utf-8")
                except OSError:
                    continue
                concept = md_path.stem if root == self._structure.concepts_dir else md_path.relative_to(root).as_posix()
                for match in _MARKDOWN_IMAGE_RE.finditer(content):
                    target = Path(match.group(1).strip()).name
                    if target:
                        refs.setdefault(target, set()).add(concept)
        return {name: sorted(values) for name, values in refs.items()}

    def get_stats(self) -> AssetIndexStats:
        files = self._list_asset_files()
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT index_status, COUNT(*) AS cnt FROM wiki_assets_meta GROUP BY index_status"
            )
            counts = {str(row["index_status"]): int(row["cnt"]) for row in cursor.fetchall()}
        indexed = counts.get("indexed", 0)
        failed = counts.get("failed", 0)
        pending = max(0, len(files) - indexed - failed)
        return AssetIndexStats(indexed=indexed, pending=pending, failed=failed, total_files=len(files))

    def _list_asset_files(self) -> list[Path]:
        assets = self.assets_dir
        if not assets.is_dir():
            return []
        return sorted(
            path
            for path in assets.iterdir()
            if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
        )

    async def _ensure_collection(self) -> None:
        if not self._vector or not self._embedding or self._collection_ready:
            return
        try:
            test_vec = await self._embedding.embed("test")
            dim = len(test_vec)
            if hasattr(self._vector, "ensure_collection"):
                await self._vector.ensure_collection(_COLLECTION_NAME, dim)
            elif hasattr(self._vector, "create_collection"):
                exists = await self._vector.collection_exists(_COLLECTION_NAME)
                if not exists:
                    await self._vector.create_collection(_COLLECTION_NAME, dim)
            self._collection_ready = True
        except Exception as exc:
            logger.warning("Failed to ensure wiki_assets vector collection: %s", exc)

    async def index_file(self, path: Path, *, provenance: list[str] | None = None) -> bool:
        if not self._config.enable_asset_index or self._caption_provider is None:
            return False
        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            return False

        filename = path.name
        file_hash = await asyncio.to_thread(self._sha256_file, path)

        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT sha256, index_status FROM wiki_assets_meta WHERE filename = ?",
                (filename,),
            )
            row = cursor.fetchone()
            if row and str(row["sha256"]) == file_hash and str(row["index_status"]) == "indexed":
                return False

        try:
            caption = (await self._caption_provider.caption_file(path)).strip()
        except Exception as exc:
            logger.error("Asset caption failed for %s: %s", filename, exc)
            self._mark_status(filename, file_hash, "", provenance or [], "failed")
            return False

        if not caption:
            self._mark_status(filename, file_hash, "", provenance or [], "failed")
            return False

        await self._upsert_index(filename, file_hash, caption, provenance or [])
        return True

    def _mark_status(
        self,
        filename: str,
        file_hash: str,
        caption: str,
        source_concepts: list[str],
        status: str,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO wiki_assets_meta
                (filename, sha256, caption, source_concepts, indexed_at, index_status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (filename, file_hash, caption, json.dumps(source_concepts), now, status),
            )

    async def _upsert_index(
        self,
        filename: str,
        file_hash: str,
        caption: str,
        source_concepts: list[str],
    ) -> None:
        now = datetime.now(UTC).isoformat()
        concepts_json = json.dumps(source_concepts)

        def sync_upsert() -> None:
            with self._get_conn() as conn:
                conn.execute("DELETE FROM wiki_assets_fts WHERE filename = ?", (filename,))
                conn.execute(
                    "INSERT INTO wiki_assets_fts (filename, caption) VALUES (?, ?)",
                    (filename, caption),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO wiki_assets_meta
                    (filename, sha256, caption, source_concepts, indexed_at, index_status)
                    VALUES (?, ?, ?, ?, ?, 'indexed')
                    """,
                    (filename, file_hash, caption, concepts_json, now),
                )

        await asyncio.to_thread(sync_upsert)

        if self._config.enable_hybrid_search and self._vector and self._embedding:
            await self._ensure_collection()
            await upsert_text_vectors(
                embedding=self._embedding,
                vector=self._vector,
                collection_name=_COLLECTION_NAME,
                parent_key=filename,
                text=caption,
                base_metadata={
                    "filename": filename,
                    "entry_type": "asset",
                    "source_concepts": source_concepts,
                },
                metadata_key="filename",
            )

    async def index_all(self) -> AssetIndexResult:
        if not self._config.enable_asset_index or self._caption_provider is None:
            return AssetIndexResult(indexed=0, skipped=0, failed=0)

        provenance_map = self.scan_image_references()
        indexed = 0
        skipped = 0
        failed = 0
        for path in self._list_asset_files():
            before_hash = self._existing_hash(path.name)
            if before_hash == await asyncio.to_thread(self._sha256_file, path):
                with self._get_conn() as conn:
                    row = conn.execute(
                        "SELECT index_status FROM wiki_assets_meta WHERE filename = ?",
                        (path.name,),
                    ).fetchone()
                    if row and str(row["index_status"]) == "indexed":
                        skipped += 1
                        continue

            ok = await self.index_file(path, provenance=provenance_map.get(path.name, []))
            if ok:
                indexed += 1
            else:
                with self._get_conn() as conn:
                    row = conn.execute(
                        "SELECT index_status FROM wiki_assets_meta WHERE filename = ?",
                        (path.name,),
                    ).fetchone()
                    if row and str(row["index_status"]) == "failed":
                        failed += 1
                    else:
                        skipped += 1

        purged = await self.purge_orphan_entries()
        if purged:
            logger.info("Purged %d orphan wiki asset index entries", purged)

        return AssetIndexResult(indexed=indexed, skipped=skipped, failed=failed)

    async def purge_orphan_entries(self) -> int:
        """Remove FTS/meta/vector rows for assets no longer present on disk."""
        on_disk = {path.name for path in self._list_asset_files()}

        def sync_list_meta() -> list[str]:
            with self._get_conn() as conn:
                cursor = conn.execute("SELECT filename FROM wiki_assets_meta")
                return [str(row["filename"]) for row in cursor.fetchall()]

        indexed_filenames = await asyncio.to_thread(sync_list_meta)
        purged = 0
        for filename in indexed_filenames:
            if filename not in on_disk:
                await self.delete_file(filename)
                purged += 1
        return purged

    def _existing_hash(self, filename: str) -> str | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT sha256 FROM wiki_assets_meta WHERE filename = ?", (filename,)).fetchone()
            return str(row["sha256"]) if row else None

    async def delete_file(self, filename: str) -> None:
        def sync_delete() -> None:
            with self._get_conn() as conn:
                conn.execute("DELETE FROM wiki_assets_fts WHERE filename = ?", (filename,))
                conn.execute("DELETE FROM wiki_assets_meta WHERE filename = ?", (filename,))

        await asyncio.to_thread(sync_delete)
        if self._config.enable_hybrid_search and self._vector and hasattr(self._vector, "delete"):
            with contextlib.suppress(Exception):
                await self._vector.delete(_COLLECTION_NAME, [self._asset_to_uuid(filename)])

    async def search(self, query: str, limit: int = 5) -> list[AssetSearchHit]:
        if not self._config.enable_asset_index:
            return []
        safe_query = query.replace('"', "").replace("'", "").strip()
        if not safe_query:
            return []

        fts_results: list[tuple[str, float]] = []

        def sync_fts() -> list[tuple[str, float]]:
            results: list[tuple[str, float]] = []
            fts_query = tokenize_for_fts(safe_query)
            if not fts_query:
                return results
            with self._get_conn() as conn:
                try:
                    cursor = conn.execute(
                        """
                        SELECT filename, rank FROM wiki_assets_fts
                        WHERE wiki_assets_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (fts_query, limit * 2),
                    )
                    for row in cursor.fetchall():
                        score = 1.0 / (abs(float(row["rank"])) + 1.0)
                        results.append((str(row["filename"]), score))
                except sqlite3.OperationalError as exc:
                    logger.error("Asset FTS search error: %s", exc)
                    healed = fts5_auto_heal(conn, "wiki_assets_fts")
                    if healed and fts_query:
                        with contextlib.suppress(sqlite3.OperationalError):
                            cursor = conn.execute(
                                """
                                SELECT filename, rank FROM wiki_assets_fts
                                WHERE wiki_assets_fts MATCH ?
                                ORDER BY rank
                                LIMIT ?
                                """,
                                (fts_query, limit * 2),
                            )
                            for row in cursor.fetchall():
                                score = 1.0 / (abs(float(row["rank"])) + 1.0)
                                results.append((str(row["filename"]), score))
            return results

        fts_results = await asyncio.to_thread(sync_fts)

        vec_results: list[tuple[str, float]] = []
        if self._config.enable_hybrid_search and self._vector and self._embedding:
            await self._ensure_collection()
            try:
                query_vec = await self._embedding.embed(safe_query)
                search_res = await self._vector.search(_COLLECTION_NAME, query_vector=query_vec, limit=limit * 2)
                for res in search_res:
                    filename = str(res.document.metadata.get("filename", res.document.id))
                    vec_results.append((filename, res.score))
            except Exception as exc:
                logger.error("Wiki asset vector search failed: %s", exc)

        if self._config.enable_hybrid_search and self._vector and self._embedding and (fts_results or vec_results):
            fused = rrf_fusion([fts_results, vec_results], k=getattr(self._config, "rrf_k", 60))
        else:
            fused = fts_results

        fused.sort(key=lambda item: item[1], reverse=True)
        top = fused[:limit]
        hits: list[AssetSearchHit] = []
        with self._get_conn() as conn:
            for filename, score in top:
                row = conn.execute(
                    "SELECT caption, source_concepts FROM wiki_assets_meta WHERE filename = ? AND index_status = 'indexed'",
                    (filename,),
                ).fetchone()
                if row is None:
                    continue
                concepts_raw = str(row["source_concepts"] or "[]")
                try:
                    concepts = tuple(json.loads(concepts_raw))
                except json.JSONDecodeError:
                    concepts = ()
                hits.append(
                    AssetSearchHit(
                        filename=filename,
                        caption=str(row["caption"]),
                        score=score,
                        source_concepts=tuple(str(c) for c in concepts),
                    )
                )
        return hits

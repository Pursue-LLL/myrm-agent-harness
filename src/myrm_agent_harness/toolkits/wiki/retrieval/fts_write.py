"""Wiki index writes: FTS5 truth upsert/delete, raw-text interim entries, vector upsert/delete.

[INPUT]
- sqlite3 (POS: standard library database)
- myrm_agent_harness.toolkits.retriever.cjk_tokenizer::build_cjk_index_segment (POS: FTS CJK write-side token segment builder)
- myrm_agent_harness.toolkits.retriever.embedding.window_policy::EmbedInputTooLargeError (POS: embedding input window violation)
- ..core.config::WikiConfig (POS: wiki configuration center)
- ..core.frontmatter_contract::WikiPublishStatus, resolve_publish_status (POS: publish_status SSOT)
- ..core.link_resolver::WikiLinkResolver (POS: link target resolution; notified when a page is deleted)
- .edge_links::linkers_to_reread, relink_dangling_edges (POS: edges of links that named a deleted page converge)
- .edge_weights::refresh_edge_weights (POS: edges that pointed at a deleted page are re-weighted)
- .vector_chunks::delete_text_vectors, upsert_text_vectors (POS: L2 chunk vector operations)

[OUTPUT]
- FtsWriteMixin: FTS5 + vector upsert/delete and raw-text interim indexing for WikiIndexer; pages are keyed by their on-disk path, delete accepts any spelling

[POS]
Wiki index write operations mixin. Keeps everything that changes the index (truth rows,
publish gate, graph edges of the written page, vectors) apart from the read side in
`FtsSearchMixin`, so each module stays single-responsibility and within size limits.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.retriever.cjk_tokenizer import build_cjk_index_segment
from myrm_agent_harness.toolkits.retriever.embedding.window_policy import (
    EmbedInputTooLargeError,
)

from ..core.config import WikiConfig
from ..core.frontmatter_contract import WikiPublishStatus, resolve_publish_status
from .edge_links import linkers_to_reread, relink_dangling_edges
from .edge_weights import refresh_edge_weights
from .vector_chunks import delete_text_vectors, upsert_text_vectors

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from contextlib import AbstractContextManager

    from myrm_agent_harness.toolkits.memory.protocols.embedding import (
        EmbeddingProtocol,
    )
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

    from ..core.link_resolver import WikiLinkResolver

logger = logging.getLogger(__name__)


class FtsWriteMixin:
    """FTS5 truth storage plus vector upsert/delete operations for WikiIndexer.

    Expects the host class to provide: _get_conn, _config, _vector, _embedding,
    _collection_name, _ensure_collection, _concept_dir_path, _index_key,
    _concept_name_variants, _link_resolver, extract_and_upsert_edges and
    _reread_page_links.
    """

    _config: WikiConfig
    _vector: VectorStoreProtocol | None
    _embedding: EmbeddingProtocol | None
    _collection_name: str

    if TYPE_CHECKING:
        # Attributes provided by the host class (WikiIndexer); only for type checking.
        _get_conn: Callable[[], AbstractContextManager[sqlite3.Connection]]
        _ensure_collection: Callable[[], Awaitable[None]]
        _concept_dir_path: Callable[[str], str]
        _index_key: Callable[[str], str]
        _concept_name_variants: Callable[[str], tuple[str, ...]]
        _link_resolver: WikiLinkResolver
        extract_and_upsert_edges: Callable[[str, str], None]
        _reread_page_links: Callable[[Sequence[str]], None]

    def remove_raw_text_index(self, name: str) -> None:
        """Remove interim raw FTS entry (see :meth:`index_raw_text`)."""
        raw_key = f"raw:{name}"
        with self._get_conn() as conn:
            conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (raw_key,))

    def index_raw_text(self, name: str, text: str) -> None:
        """Index raw text into FTS5 for immediate searchability before compilation.

        Uses a ``raw:`` prefix to distinguish from compiled entries. When the
        compiled version is later upserted via :meth:`upsert`, it replaces
        this interim entry.
        """
        raw_key = f"raw:{name}"
        preview = text[:5000] if len(text) > 5000 else text
        indexed_content = build_cjk_index_segment(f"{name} {preview}")

        with self._get_conn() as conn:
            conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (raw_key,))
            conn.execute(
                "INSERT INTO wiki_fts (concept_name, truth_content, search_terms) VALUES (?, ?, ?)",
                (raw_key, preview, indexed_content),
            )

    @staticmethod
    def _resolve_publish_status(full_markdown: str) -> str:
        return resolve_publish_status(full_markdown).value

    async def upsert(self, concept_name: str, full_markdown: str) -> None:
        """
        Extract Compiled Truth and upsert into FTS5 index, graph edges and Vector Store.

        The page is indexed under its on-disk identity, so a compile name and the
        sanitized path of the same page never produce two index rows. The page's links
        are stored here and nowhere else: callers that write a page call this once.
        """
        concept_name = self._index_key(concept_name)
        truth_content = self._extract_truth(full_markdown)
        publish_status = self._resolve_publish_status(full_markdown)

        def sync_upsert() -> None:
            search_terms = build_cjk_index_segment(f"{concept_name} {truth_content}")
            with self._get_conn() as conn:
                conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (concept_name,))
                conn.execute(
                    "DELETE FROM wiki_fts WHERE concept_name = ?",
                    (f"raw:{concept_name}",),
                )
                conn.execute(
                    "INSERT INTO wiki_fts (concept_name, truth_content, search_terms) VALUES (?, ?, ?)",
                    (concept_name, truth_content, search_terms),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO wiki_index_meta (concept_name, publish_status) VALUES (?, ?)",
                    (concept_name, publish_status),
                )
            try:
                self.extract_and_upsert_edges(concept_name, full_markdown)
            except Exception as e:
                logger.warning("Failed to extract edges for %s: %s", concept_name, e)

        await asyncio.to_thread(sync_upsert)

        # 2. Upsert to Vector Store (Async) — published entries only
        if (
            publish_status == WikiPublishStatus.PUBLISHED.value
            and self._config.enable_hybrid_search
            and self._vector
            and self._embedding
        ):
            await self._ensure_collection()
            try:
                await upsert_text_vectors(
                    embedding=self._embedding,
                    vector=self._vector,
                    collection_name=self._collection_name,
                    parent_key=concept_name,
                    text=truth_content,
                    base_metadata={
                        "concept_name": concept_name,
                        "entry_type": "concept",
                        "level": "L2",
                        "dir_path": self._concept_dir_path(concept_name),
                    },
                    metadata_key="concept_name",
                )
            except EmbedInputTooLargeError:
                # Window violations must surface (reindex layer reports them); other
                # vector failures degrade gracefully to FTS-only.
                raise
            except Exception as e:
                logger.warning(f"Vector upsert failed for wiki concept '{concept_name}', keeping FTS only: {e}")

    async def delete(self, concept_name: str) -> None:
        """
        Delete concept from FTS5 index, its outgoing Edges, and Vector Store.

        Removes the concept under every spelling it may be indexed by (as given and as
        its on-disk path), so deleting by compile name or by path both succeed. Edges
        other pages hold to the concept stay: the links are still written in those
        pages, they read as unresolved while the page is gone and name it again when
        it returns. A link that named the concept together with another page of the
        same name reads unambiguous again, so the pages that linked to the concept are
        re-read and edges spelled like it re-resolve.
        """
        names = self._concept_name_variants(concept_name)

        # 1. Delete from SQLite FTS5 and edges (Sync wrapped in async thread)
        def sync_delete() -> None:
            changes = [(name, self._link_resolver.forget_page(name)) for name in names]
            linkers: set[str] = set()
            with self._get_conn() as conn:
                for name in names:
                    conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", (name,))
                    conn.execute("DELETE FROM wiki_edges WHERE source = ?", (name,))
                    conn.execute(
                        "DELETE FROM wiki_index_meta WHERE concept_name = ?",
                        (name,),
                    )
                # The deleted pages no longer link anywhere, which changes the weight of the edges that point at them.
                refresh_edge_weights(conn, names)
                for name, change in changes:
                    linkers.update(linkers_to_reread(conn, name, change, removed=True))
                    relink_dangling_edges(conn, self._link_resolver, change)
            self._reread_page_links(sorted(linkers - set(names)))

        await asyncio.to_thread(sync_delete)

        # 2. Delete from Vector Store (Async)
        if self._config.enable_hybrid_search and self._vector:
            for name in names:
                try:
                    await delete_text_vectors(
                        self._vector,
                        self._collection_name,
                        name,
                        metadata_key="concept_name",
                    )
                except Exception as e:
                    logger.error(f"Failed to delete vector for wiki concept '{name}': {e}")

    @staticmethod
    def _extract_truth(content: str) -> str:
        """Extract only YAML and Compiled Truth from full markdown."""
        truth_content = ""

        # 1. Extract YAML
        yaml_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if yaml_match:
            truth_content += f"---\n{yaml_match.group(1)}\n---\n\n"

        # 2. Extract Truth section
        truth_match = re.search(r"(## Compiled Truth\n.*?)(?=\n## |$)", content, re.DOTALL)
        if truth_match:
            truth_content += truth_match.group(1).strip()
        else:
            # Fallback
            truth_content = content

        return truth_content

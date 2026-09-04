"""Wiki HITL pending edits manager.

[INPUT]
sqlite3 (POS: standard library database)
typing::Literal, TypedDict (POS: standard library types)
..core.structure::WikiStructure (POS: database path resolution)

[OUTPUT]
WikiPendingEditsManager: SQLite-driven pending review draft manager
PendingWikiEdit: draft type definition
count_synthesis_pending: SQL count of Comparisons/* evolution drafts
approve_edit: publish + evolution synthesis timeline backlinks

[POS]
Implements Human-in-the-loop (HITL) knowledge review mechanism. Intercepts LLM-generated
wiki document modifications and persists them as drafts. Originals are only overwritten after
user review, preventing AI hallucinations from polluting the personal knowledge base.
Evolution synthesis pages from CCSP share the same queue under Comparisons/* paths.
"""

import contextlib
import sqlite3
from typing import TYPE_CHECKING, Literal, TypedDict

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import assert_valid_wiki_frontmatter
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.publication import publish_concept_article

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


class PendingWikiEdit(TypedDict):
    id: int
    concept_name: str
    proposed_content: str
    status: Literal["pending", "approved", "rejected"]
    created_at: str
    provenance: str | None


class WikiPendingEditsManager:
    """Manages Human-in-the-loop pending wiki edits."""

    def __init__(self, structure: WikiStructure, indexer: "WikiIndexer | None" = None):
        self._structure = structure
        self._indexer = indexer
        self.db_path = self._structure.base_dir / ".pending_edits.db"
        self._init_db()

    @contextlib.contextmanager
    def _get_conn(self):
        from myrm_agent_harness.utils.db.sqlite import DEFAULT, harden_connection_sync

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        harden_connection_sync(conn, DEFAULT, db_path=self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_edits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    concept_name TEXT NOT NULL,
                    proposed_content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    provenance TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON pending_edits(status)")
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE pending_edits ADD COLUMN provenance TEXT")

    async def stage_pending_edit(
        self,
        concept_name: str,
        proposed_content: str,
        *,
        source_files: list[str] | None = None,
        provenance: str | None = None,
    ) -> int:
        """Stage a pending draft and demote stale published articles from RAG."""
        from myrm_agent_harness.toolkits.wiki.pipeline.publication.stale_guard import (
            demote_stale_published_article,
            sources_newer_than_article,
        )

        if sources_newer_than_article(
            self._structure,
            concept_name,
            proposed_content,
            source_files=source_files,
        ):
            await demote_stale_published_article(self._structure, self._indexer, concept_name)
        return self.add_pending_edit(concept_name, proposed_content, provenance=provenance)

    def add_pending_edit(self, concept_name: str, proposed_content: str, *, provenance: str | None = None) -> int:
        """Add a new draft edit. If one exists for the same concept, overwrite it."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE pending_edits SET status = 'rejected' WHERE concept_name = ? AND status = 'pending'",
                (concept_name,),
            )
            cursor = conn.execute(
                """
                INSERT INTO pending_edits (concept_name, proposed_content, status, created_at, provenance)
                VALUES (?, ?, 'pending', CURRENT_TIMESTAMP, ?)
                """,
                (concept_name, proposed_content, provenance),
            )
            return cursor.lastrowid or 0

    def get_pending_edits(self, limit: int = 50) -> list[PendingWikiEdit]:
        """Get list of pending drafts."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM pending_edits WHERE status = 'pending' ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            # The type ignore is needed because sqlite3.Row isn't exactly matching TypedDict
            return [dict(row) for row in cursor.fetchall()]  # type: ignore

    async def approve_edit(self, edit_id: int, modified_content: str | None = None) -> bool:
        """Approve an edit, write to file system, and upsert FTS5 index. Returns True if successful."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT concept_name, proposed_content FROM pending_edits WHERE id = ? AND status = 'pending'",
                (edit_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False

            concept_name = row["concept_name"]
            proposed_content = row["proposed_content"]

            # Use modified_content if provided by user inline editing, otherwise use original draft
            final_content = modified_content if modified_content is not None else proposed_content

            assert_valid_wiki_frontmatter(final_content)

            from myrm_agent_harness.toolkits.wiki.pipeline.publication.stale_guard import (
                StalePendingApprovalError,
                sources_newer_than_article,
            )

            if sources_newer_than_article(self._structure, concept_name, final_content):
                raise StalePendingApprovalError(
                    "Source files updated since this draft was staged. Recompile before approving."
                )

            await publish_concept_article(
                self._structure,
                self._indexer,
                concept_name,
                final_content,
            )

            from myrm_agent_harness.toolkits.wiki.pipeline.contradiction_synthesis import (
                apply_synthesis_backlinks,
            )

            await apply_synthesis_backlinks(
                self._structure,
                self._indexer,
                synthesis_concept_name=concept_name,
                synthesis_content=final_content,
            )

            # Update DB
            conn.execute("UPDATE pending_edits SET status = 'approved' WHERE id = ?", (edit_id,))
            return True

    def reject_edit(self, edit_id: int) -> bool:
        """Reject an edit."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE pending_edits SET status = 'rejected' WHERE id = ? AND status = 'pending'", (edit_id,)
            )
            return cursor.rowcount > 0

    def count_synthesis_pending(self) -> int:
        """Count pending evolution synthesis drafts (Comparisons/.../Evolution)."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM pending_edits
                WHERE status = 'pending' AND concept_name LIKE 'Comparisons/%'
                """
            )
            row = cursor.fetchone()
            return int(row["count"]) if row else 0

    def get_stats(self) -> dict[str, int]:
        """Get stats for pending edits."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT status, COUNT(*) as count FROM pending_edits GROUP BY status")
            stats = {"pending": 0, "approved": 0, "rejected": 0}
            for row in cursor.fetchall():
                status = row["status"]
                if status in stats:
                    stats[status] = row["count"]
            return stats


WikiPendingManager = WikiPendingEditsManager

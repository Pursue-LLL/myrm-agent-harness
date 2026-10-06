# [POS] toolkits/memory/wiki_memory/engine.py
# [INPUT] pathlib.Path, types, wiki_store.MarkdownWikiMemoryStore, git_auditor.WikiGitAuditor, derived_indexer.DerivedWikiSqliteIndexer
# [OUTPUT] WikiMemoryEngine

"""Facade orchestrator coordinating Markdown-as-SSOT storage, Git audit, and derived FTS5 indexing."""

from __future__ import annotations

from pathlib import Path

from .derived_indexer import DerivedWikiSqliteIndexer
from .git_auditor import WikiGitAuditor
from .types import (
    WikiAuditCommit,
    WikiIndexRebuildResult,
    WikiLinkRef,
    WikiMemoryPage,
    WikiScopeLevel,
    WikiSearchMatch,
)
from .wiki_store import MarkdownWikiMemoryStore


class WikiMemoryEngine:
    """Unified engine coordinating Markdown SSOT storage, Git auditing, and derived SQLite indexing."""

    def __init__(
        self,
        base_dir: Path,
        store: MarkdownWikiMemoryStore | None = None,
        auditor: WikiGitAuditor | None = None,
        indexer: DerivedWikiSqliteIndexer | None = None,
    ) -> None:
        self._base_dir = base_dir
        self._wiki_root = base_dir / "memory_wiki"
        self._db_path = base_dir / "derived_cache" / "wiki_derived.sqlite"

        self._store = store or MarkdownWikiMemoryStore(root_dir=self._wiki_root)
        self._auditor = auditor or WikiGitAuditor(repo_root=self._wiki_root)
        self._indexer = indexer or DerivedWikiSqliteIndexer(db_path=self._db_path)

        # Ensure Git repo is initialized
        self._auditor.init_repo()

    def save_page(
        self,
        page: WikiMemoryPage,
        commit_message: str | None = None,
        author: str = "Myrm Memory Auditor",
    ) -> WikiAuditCommit | None:
        """Persist memory page to Markdown SSOT, update derived FTS index, and commit to Git."""
        # 1. Save to physical Markdown file
        saved_path = self._store.save_page(page)

        # 2. Extract links and update derived SQLite index
        links = self._store.extract_links(page.page_id, page.content)
        self._indexer.index_page(
            page_id=page.page_id,
            title=page.title,
            content=page.content,
            scope=page.scope,
            profile_id=page.profile_id,
            tags=page.tags,
            links=links,
            updated_at=page.updated_at,
        )

        # 3. Create Git version audit commit
        msg = commit_message or f"chore(memory): update wiki page [{page.title}] in {page.scope.value}"
        commit = self._auditor.commit_change(
            file_paths=[saved_path],
            message=msg,
            author=author,
        )
        return commit

    def get_page(
        self,
        page_id: str,
        scope: WikiScopeLevel,
        profile_id: str | None = None,
    ) -> WikiMemoryPage | None:
        """Fetch memory page directly from the Markdown source of truth."""
        return self._store.get_page(page_id=page_id, scope=scope, profile_id=profile_id)

    def delete_page(
        self,
        page_id: str,
        scope: WikiScopeLevel,
        profile_id: str | None = None,
        commit_message: str | None = None,
        author: str = "Myrm Memory Auditor",
    ) -> bool:
        """Remove Markdown page, clean derived index, and commit deletion to Git."""
        target_path = self._store.resolve_page_path(page_id=page_id, scope=scope, profile_id=profile_id)
        deleted = self._store.delete_page(page_id=page_id, scope=scope, profile_id=profile_id)
        if not deleted:
            return False

        # Clean derived index
        self._indexer.remove_page(page_id=page_id)

        # Commit deletion in Git
        msg = commit_message or f"chore(memory): delete wiki page [{page_id}] from {scope.value}"
        self._auditor.commit_change(file_paths=[target_path], message=msg, author=author)
        return True

    def list_pages(
        self,
        scope: WikiScopeLevel | None = None,
        profile_id: str | None = None,
    ) -> list[WikiMemoryPage]:
        """List all Markdown pages matching scope criteria."""
        return self._store.list_pages(scope=scope, profile_id=profile_id)

    def search(
        self,
        query: str,
        scope: WikiScopeLevel | None = None,
        profile_id: str | None = None,
        limit: int = 10,
    ) -> list[WikiSearchMatch]:
        """Execute accelerated full-text search against the derived SQLite FTS5 index."""
        return self._indexer.search(query=query, scope=scope, profile_id=profile_id, limit=limit)

    def get_backlinks(self, page_title: str) -> list[WikiLinkRef]:
        """Query incoming Obsidian backlinks referencing the target page title."""
        return self._indexer.get_backlinks(target_page_title=page_title)

    def get_history(self, limit: int = 20) -> list[WikiAuditCommit]:
        """Retrieve recent Git version audit commits."""
        return self._auditor.get_history(limit=limit)

    def revert_change(self, commit_hash: str) -> bool:
        """Revert a git commit to undo hallucinated or erroneous memory mutations."""
        success = self._auditor.revert_commit(commit_hash=commit_hash)
        if success:
            # Recompile derived index after git revert
            self.rebuild_derived_index()
        return success

    def rebuild_derived_index(self) -> WikiIndexRebuildResult:
        """Rebuild entire SQLite FTS5 and link graph index 100% from Markdown files."""
        all_pages = self._store.list_pages()
        tuples_to_index: list[tuple[str, str, str, WikiScopeLevel, str | None, list[str], list[WikiLinkRef], float]] = []

        for p in all_pages:
            tuples_to_index.append(
                (
                    p.page_id,
                    p.title,
                    p.content,
                    p.scope,
                    p.profile_id,
                    p.tags,
                    p.links,
                    p.updated_at,
                )
            )

        return self._indexer.rebuild_all_from_markdown(tuples_to_index)

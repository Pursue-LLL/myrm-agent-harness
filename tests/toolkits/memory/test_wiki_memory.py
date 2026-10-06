# [POS] tests/toolkits/memory/test_wiki_memory.py
# [INPUT] myrm_agent_harness.toolkits.memory.wiki_memory
# [OUTPUT] Unit tests verifying Markdown-as-SSOT, Git auditing, and derived SQLite FTS5 rebuild

"""Unit tests for Markdown-as-SSOT Wiki Memory Engine."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.memory.wiki_memory import (
    MarkdownWikiMemoryStore,
    WikiMemoryEngine,
    WikiMemoryPage,
    WikiScopeLevel,
)


def test_wiki_store_markdown_and_links(tmp_path: Path) -> None:
    """Verify Markdown file generation with YAML frontmatter and Obsidian link extraction."""
    store = MarkdownWikiMemoryStore(root_dir=tmp_path / "wiki")

    page_content = (
        "This is an architectural decision.\n"
        "See [[DatabaseSchema]] for details.\n"
        "Also refer to [[FastApiBestPractices#Middleware|FastAPI Guidelines]]."
    )

    page = WikiMemoryPage(
        page_id="arch_decision_01",
        title="Architecture Decision 01",
        content=page_content,
        scope=WikiScopeLevel.GLOBAL,
        tags=["architecture", "decision"],
        frontmatter={"author": "lead_architect", "status": "approved"},
    )

    saved_path = store.save_page(page)
    assert saved_path.is_file()
    assert saved_path.name == "arch_decision_01.md"

    # Verify physical Markdown content
    raw_text = saved_path.read_text(encoding="utf-8")
    assert "---" in raw_text
    assert "scope: global" in raw_text
    assert "tags: [architecture, decision]" in raw_text
    assert "author: lead_architect" in raw_text
    assert "[[DatabaseSchema]]" in raw_text

    # Read back through store
    loaded = store.get_page("arch_decision_01", scope=WikiScopeLevel.GLOBAL)
    assert loaded is not None
    assert loaded.title == "Architecture Decision 01"
    assert loaded.tags == ["architecture", "decision"]
    assert len(loaded.links) == 2

    # Check extracted link details
    l1 = loaded.links[0]
    assert l1.target_page_title == "DatabaseSchema"
    assert l1.link_text == "DatabaseSchema"

    l2 = loaded.links[1]
    assert l2.target_page_title == "FastApiBestPractices"
    assert l2.section == "Middleware"
    assert l2.link_text == "FastAPI Guidelines"


def test_scoped_hierarchy_isolation(tmp_path: Path) -> None:
    """Verify physical path isolation between global and agent-scoped tiers."""
    store = MarkdownWikiMemoryStore(root_dir=tmp_path / "wiki")

    # 1. Global page
    p_global = WikiMemoryPage(
        page_id="company_standards",
        title="Company Standards",
        content="General rules for all agents.",
        scope=WikiScopeLevel.GLOBAL,
    )
    store.save_page(p_global)

    # 2. Agent Coder private page
    p_coder = WikiMemoryPage(
        page_id="python_concurrency",
        title="Python Concurrency Rules",
        content="Always use asyncio.gather.",
        scope=WikiScopeLevel.AGENT,
        profile_id="coder_profile",
    )
    store.save_page(p_coder)

    # 3. Agent Tester private page
    p_tester = WikiMemoryPage(
        page_id="test_fixtures",
        title="Pytest Fixture Rules",
        content="Use module-scoped fixtures.",
        scope=WikiScopeLevel.AGENT,
        profile_id="tester_profile",
    )
    store.save_page(p_tester)

    # Verify physical file locations
    assert (tmp_path / "wiki" / "global" / "company_standards.md").is_file()
    assert (tmp_path / "wiki" / "agents" / "coder_profile" / "python_concurrency.md").is_file()
    assert (tmp_path / "wiki" / "agents" / "tester_profile" / "test_fixtures.md").is_file()

    # Scope listing verification
    coder_pages = store.list_pages(profile_id="coder_profile")
    coder_ids = [p.page_id for p in coder_pages]
    assert "company_standards" in coder_ids
    assert "python_concurrency" in coder_ids
    assert "test_fixtures" not in coder_ids  # Isolated from tester profile!


def test_git_auditing_and_version_history(tmp_path: Path) -> None:
    """Verify Git commits are created upon page modification and history is trackable."""
    engine = WikiMemoryEngine(base_dir=tmp_path)

    page = WikiMemoryPage(
        page_id="system_architecture",
        title="System Architecture",
        content="Initial architecture design.",
        scope=WikiScopeLevel.GLOBAL,
    )

    commit1 = engine.save_page(page, commit_message="feat(wiki): add system architecture")
    assert commit1 is not None
    assert commit1.commit_hash

    # Update page content
    page_updated = WikiMemoryPage(
        page_id="system_architecture",
        title="System Architecture",
        content="Updated architecture design with microservices.",
        scope=WikiScopeLevel.GLOBAL,
    )
    commit2 = engine.save_page(page_updated, commit_message="fix(wiki): refine architecture to microservices")
    assert commit2 is not None

    # Retrieve history
    history = engine.get_history(limit=5)
    assert len(history) >= 2
    messages = [c.message for c in history]
    assert any("refine architecture" in m for m in messages)


def test_derived_sqlite_fts_and_backlinks(tmp_path: Path) -> None:
    """Verify FTS5 full-text search and Obsidian backlink graph queries."""
    engine = WikiMemoryEngine(base_dir=tmp_path)

    # Page 1: mentions database migration
    p1 = WikiMemoryPage(
        page_id="db_design",
        title="Database Design",
        content="PostgreSQL table schemas and [[MigrationGuide]].",
        scope=WikiScopeLevel.GLOBAL,
        tags=["database", "postgres"],
    )
    engine.save_page(p1)

    # Page 2: another page also mentioning MigrationGuide
    p2 = WikiMemoryPage(
        page_id="deployment_runbook",
        title="Deployment Runbook",
        content="Before deployment, execute [[MigrationGuide]].",
        scope=WikiScopeLevel.GLOBAL,
        tags=["deploy"],
    )
    engine.save_page(p2)

    # 1. Full-text search
    matches = engine.search("PostgreSQL", limit=5)
    assert len(matches) >= 1
    assert matches[0].page_id == "db_design"

    # 2. Backlinks query for MigrationGuide
    backlinks = engine.get_backlinks("MigrationGuide")
    assert len(backlinks) == 2
    source_ids = [b.source_page_id for b in backlinks]
    assert "db_design" in source_ids
    assert "deployment_runbook" in source_ids


def test_derived_index_cold_rebuild_from_markdown(tmp_path: Path) -> None:
    """Verify SQLite derived index can be 100% idempotently reconstructed from Markdown SSOT."""
    engine = WikiMemoryEngine(base_dir=tmp_path)

    p1 = WikiMemoryPage(
        page_id="resilience_pattern",
        title="Resilience Pattern",
        content="Circuit breakers and exponential backoff.",
        scope=WikiScopeLevel.GLOBAL,
    )
    engine.save_page(p1)

    p2 = WikiMemoryPage(
        page_id="cache_invalidation",
        title="Cache Invalidation",
        content="Cache-aside with TTL and [[ResiliencePattern]].",
        scope=WikiScopeLevel.AGENT,
        profile_id="backend_bot",
    )
    engine.save_page(p2)

    # Simulate catastrophic loss of derived SQLite database
    db_file = tmp_path / "derived_cache" / "wiki_derived.sqlite"
    assert db_file.exists()
    db_file.unlink()

    # Rebuild from physical Markdown files
    rebuild_res = engine.rebuild_derived_index()
    assert rebuild_res.status == "success"
    assert rebuild_res.rebuilt_pages == 2
    assert rebuild_res.rebuilt_links == 1

    # Search works again immediately
    matches = engine.search("exponential backoff")
    assert len(matches) == 1
    assert matches[0].page_id == "resilience_pattern"

    # Backlinks work again immediately
    backlinks = engine.get_backlinks("ResiliencePattern")
    assert len(backlinks) == 1
    assert backlinks[0].source_page_id == "cache_invalidation"

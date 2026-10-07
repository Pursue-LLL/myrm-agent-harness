"""[POS]: tests/unit/toolkits/memory/test_four_tier_fts_suite.py
[INPUT]: Isolated tmp_path directory, four-tier memory items, and search queries.
[OUTPUT]: Comprehensive unit tests verifying 4-tier scopes, SQLite FTS5 BM25 ranked recall, and /dream compaction cycles.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from myrm_agent_harness.toolkits.memory import (
    FourTierDreamCompactor,
    FourTierMemoryItem,
    MemoryScope,
    SqliteFts5MemoryEngine,
)


def test_four_tier_scopes_and_project_hash_isolation(tmp_path: Path) -> None:
    """Verifies persistence across all 4 tiers and cross-project database isolation."""
    engine = SqliteFts5MemoryEngine(base_storage_dir=tmp_path / "memory_db")

    # 1. Save items across 4 scopes for Project Alpha
    proj_a = "proj_alpha_hash"
    item_global = FourTierMemoryItem(
        item_id="glob_001",
        scope=MemoryScope.GLOBAL,
        project_hash=proj_a,
        title="Language Preference",
        content="Always respond in concise professional Chinese.",
        tags=["preference", "language"],
    )
    item_project = FourTierMemoryItem(
        item_id="proj_001",
        scope=MemoryScope.PROJECT,
        project_hash=proj_a,
        title="Architecture Rule",
        content="Use FastAPI with dependency injection for service factories.",
        tags=["architecture", "fastapi"],
    )
    item_session = FourTierMemoryItem(
        item_id="sess_001",
        scope=MemoryScope.SESSION,
        project_hash=proj_a,
        session_id="sess_worker_12",
        title="Checkpoint Step 4",
        content="Schema migration completed, proceeding to endpoint integration.",
        tags=["checkpoint"],
    )
    item_progress = FourTierMemoryItem(
        item_id="prog_001",
        scope=MemoryScope.PROGRESS,
        project_hash=proj_a,
        title="Active Goal Status",
        content="Goal: Refactor memory router. Status: 3/5 subtasks completed.",
        tags=["todo", "goal"],
    )

    engine.save_item(item_global)
    engine.save_item(item_project)
    engine.save_item(item_session)
    engine.save_item(item_progress)

    # 2. Verify retrieval and scope filtering in Project Alpha
    all_a = engine.list_items(project_hash=proj_a)
    assert len(all_a) == 4

    projects_a = engine.list_items(project_hash=proj_a, scope=MemoryScope.PROJECT)
    assert len(projects_a) == 1
    assert projects_a[0].item_id == "proj_001"
    assert "FastAPI" in projects_a[0].content

    # 3. Verify cross-project isolation: Project Beta should have 0 items
    proj_b = "proj_beta_hash"
    all_b = engine.list_items(project_hash=proj_b)
    assert len(all_b) == 0

    # 4. Save item into Project Beta
    item_b = FourTierMemoryItem(
        item_id="proj_b_001",
        scope=MemoryScope.PROJECT,
        project_hash=proj_b,
        title="Rust Workspace Rule",
        content="Use cargo clippy with -D warnings.",
        tags=["rust", "lint"],
    )
    engine.save_item(item_b)

    assert len(engine.list_items(project_hash=proj_b)) == 1
    assert len(engine.list_items(project_hash=proj_a)) == 4


def test_sqlite_fts5_bm25_ranked_full_text_search(tmp_path: Path) -> None:
    """Verifies millisecond full-text search and BM25 relevance ranking."""
    engine = SqliteFts5MemoryEngine(base_storage_dir=tmp_path / "memory_db")
    proj = "search_demo_proj"

    # Seed knowledge entries
    item1 = FourTierMemoryItem(
        item_id="rule_sqlite_wal",
        scope=MemoryScope.PROJECT,
        project_hash=proj,
        title="SQLite Concurrency Configuration",
        content="Enable WAL mode with PRAGMA journal_mode=WAL and set busy_timeout to 5000ms.",
        tags=["sqlite", "wal", "database"],
    )
    item2 = FourTierMemoryItem(
        item_id="rule_postgres_pool",
        scope=MemoryScope.PROJECT,
        project_hash=proj,
        title="PostgreSQL Connection Pool",
        content="Configure AsyncEngine pool_size=20 with max_overflow=10.",
        tags=["postgres", "database"],
    )
    item3 = FourTierMemoryItem(
        item_id="pref_editor",
        scope=MemoryScope.GLOBAL,
        project_hash=proj,
        title="Editor Tooling",
        content="Prefer VSCode with Ruff extension enabled for inline diagnostics.",
        tags=["editor", "tooling"],
    )

    engine.save_item(item1)
    engine.save_item(item2)
    engine.save_item(item3)

    # Search for "WAL"
    wal_hits = engine.search_fts(query_text="WAL", project_hash=proj)
    assert len(wal_hits) >= 1
    assert wal_hits[0].item_id == "rule_sqlite_wal"
    assert "journal_mode" in wal_hits[0].snippet or "WAL" in wal_hits[0].snippet

    # Search for "database" across all scopes
    db_hits = engine.search_fts(query_text="database", project_hash=proj)
    assert len(db_hits) >= 2
    hit_ids = {h.item_id for h in db_hits}
    assert "rule_sqlite_wal" in hit_ids
    assert "rule_postgres_pool" in hit_ids

    # Search with scope restriction (GLOBAL only)
    global_hits = engine.search_fts(
        query_text="Ruff", project_hash=proj, scope=MemoryScope.GLOBAL
    )
    assert len(global_hits) == 1
    assert global_hits[0].item_id == "pref_editor"


def test_dream_compaction_cycle_merging_and_pruning(tmp_path: Path) -> None:
    """Verifies /dream maintenance cycle merges fragmented entries and purges stale progress items."""
    engine = SqliteFts5MemoryEngine(base_storage_dir=tmp_path / "memory_db")
    compactor = FourTierDreamCompactor(engine=engine)
    proj = "compaction_proj"

    # 1. Create duplicate fragments with the same title under PROJECT scope
    frag1 = FourTierMemoryItem(
        item_id="frag_1",
        scope=MemoryScope.PROJECT,
        project_hash=proj,
        title="Database Optimization",
        content="- Always index foreign key columns.",
        tags=["db", "indexing"],
    )
    frag2 = FourTierMemoryItem(
        item_id="frag_2",
        scope=MemoryScope.PROJECT,
        project_hash=proj,
        title="Database Optimization",
        content="- Avoid SELECT * on wide relational tables.",
        tags=["db", "performance"],
    )
    engine.save_item(frag1)
    engine.save_item(frag2)

    # 2. Create an expired PROGRESS item (older than 7 days)
    now = datetime.now(UTC)
    old_prog = FourTierMemoryItem(
        item_id="stale_todo_01",
        scope=MemoryScope.PROGRESS,
        project_hash=proj,
        title="Completed Task #89",
        content="Migrate private notebook endpoints.",
        tags=["todo"],
        created_at=now - timedelta(days=10),
        updated_at=now - timedelta(days=9),
    )
    # 3. Create a fresh PROGRESS item (updated 1 hour ago)
    fresh_prog = FourTierMemoryItem(
        item_id="active_todo_02",
        scope=MemoryScope.PROGRESS,
        project_hash=proj,
        title="Active Task #92",
        content="Implement four tier persistent memory suite.",
        tags=["todo"],
        created_at=now,
        updated_at=now,
    )
    engine.save_item(old_prog)
    engine.save_item(fresh_prog)

    # Initial check: 4 items total
    assert len(engine.list_items(project_hash=proj)) == 4

    # 4. Run /dream compaction cycle
    report = compactor.run_dream_cycle(project_hash=proj, purge_progress_days=7)
    assert report.scanned_items_count == 4
    assert report.merged_items_count == 1  # frag_2 merged into frag_1
    assert report.pruned_items_count == 1  # stale_todo_01 pruned
    assert report.retained_items_count == 2
    assert report.duration_ms >= 0.0

    # 5. Verify consolidated item content
    retained_items = engine.list_items(project_hash=proj, scope=MemoryScope.PROJECT)
    assert len(retained_items) == 1
    consolidated = retained_items[0]
    assert "foreign key" in consolidated.content
    assert "Avoid SELECT *" in consolidated.content
    assert "performance" in consolidated.tags
    assert "indexing" in consolidated.tags

    # 6. Verify stale progress is gone while fresh progress remains
    progress_items = engine.list_items(project_hash=proj, scope=MemoryScope.PROGRESS)
    assert len(progress_items) == 1
    assert progress_items[0].item_id == "active_todo_02"

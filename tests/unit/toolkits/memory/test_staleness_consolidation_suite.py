"""Unit tests for Auto Memory Staleness Decay and Consolidation Audit Suite (Item 158).

[INPUT]
- Temporary workspace fixtures, simulated timeline timestamps, fragmented memories.

[OUTPUT]
- Asserts verifying decay calculation, codebase invalidation, consolidation, and audit reports.

[POS]
- Harness test suite for Item 158 AutoMemoryStalenessDecayAndConsolidationAuditSuite.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from myrm_agent_harness.toolkits.memory.staleness_consolidation import (
    AutoMemoryStalenessAndConsolidationAuditSuite,
    ConsolidationProposal,
    MemoryAuditReport,
    MemoryConsolidationEngine,
    MemoryHalfLifeDecayProfiler,
    MemoryItemProfile,
    RepoFactInvalidationChecker,
)


def test_decay_profiler_half_life_and_touch_recall() -> None:
    profiler = MemoryHalfLifeDecayProfiler(half_life_days=30.0, staleness_threshold=0.60)
    now_dt = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Brand new item (same day)
    item_fresh = MemoryItemProfile(
        memory_id="mem_fresh_01",
        content="User prefers async python code",
        created_at="2026-10-10T11:00:00Z",
        recalled_count=0,
    )
    profiler.evaluate_item(item_fresh, now=now_dt)
    assert item_fresh.staleness_score < 0.1
    assert item_fresh.status == "active"

    # 2. Aged item without recall (60 days old = 2 half-lives)
    item_aged = MemoryItemProfile(
        memory_id="mem_aged_02",
        content="Temporary workaround for node 16 bug",
        created_at="2026-08-11T12:00:00Z",
        recalled_count=0,
    )
    profiler.evaluate_item(item_aged, now=now_dt)
    assert item_aged.staleness_score >= 0.60
    assert item_aged.status == "stale"

    # 3. Touch recall resets baseline and reduces staleness
    profiler.touch_recall(item_aged, now_iso="2026-10-10T12:00:00Z")
    assert item_aged.recalled_count == 1
    assert item_aged.staleness_score < 0.1
    assert item_aged.status == "active"


def test_repo_fact_invalidation_checker() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text('{"name": "my-app", "dependencies": {"react": "^19.0.0"}}', encoding="utf-8")

        checker = RepoFactInvalidationChecker(workspace_root=tmp_dir)

        # 1. Valid memory referencing existing path and true assertion
        mem_valid = MemoryItemProfile(
            memory_id="mem_val_01",
            content="App uses React 19 dependencies",
            referenced_paths=["package.json"],
            referenced_assertions=['contains:package.json:"react"'],
        )
        res_val = checker.check_item(mem_valid, workspace_dir=tmp_dir)
        assert res_val.is_valid is True
        assert mem_valid.status == "active"
        assert mem_valid.invalidation_reason is None

        # 2. Invalid memory referencing deleted path and false assertion
        mem_invalid = MemoryItemProfile(
            memory_id="mem_inval_02",
            content="Project uses Vue 2 legacy build",
            referenced_paths=["vue.config.js"],
            referenced_assertions=['contains:package.json:"vue"'],
        )
        res_inval = checker.check_item(mem_invalid, workspace_dir=tmp_dir)
        assert res_inval.is_valid is False
        assert "vue.config.js" in res_inval.missing_paths
        assert mem_invalid.status == "invalidated"
        assert "Missing paths" in (mem_invalid.invalidation_reason or "")


def test_memory_consolidation_engine_propose_and_apply() -> None:
    engine = MemoryConsolidationEngine(min_cluster_size=2)

    items: list[MemoryItemProfile] = [
        MemoryItemProfile(
            memory_id="mem_frag_01",
            content="Always indent with 2 spaces in TypeScript files",
            category="style_guide",
        ),
        MemoryItemProfile(
            memory_id="mem_frag_02",
            content="Use single quotes for TS strings except in JSX",
            category="style_guide",
        ),
        MemoryItemProfile(
            memory_id="mem_frag_03",
            content="Omit semicolons at statement ends in frontend code",
            category="style_guide",
        ),
        MemoryItemProfile(
            memory_id="mem_other_04",
            content="Server runs on port 8080",
            category="network",
        ),
    ]

    items_map = {it.memory_id: it for it in items}

    # Propose consolidation
    proposals: list[ConsolidationProposal] = engine.propose_consolidations(items)
    assert len(proposals) == 1
    prop = proposals[0]
    assert prop.category == "style_guide"
    assert len(prop.source_memory_ids) == 3

    # Apply consolidation
    new_item = engine.apply_consolidation(prop, items_map, now_iso="2026-10-10T12:00:00Z")
    assert new_item.memory_id.startswith("mem_cons_")
    assert new_item.status == "active"
    assert "indent with 2 spaces" in new_item.content

    # Original items marked consolidated
    for src_id in ["mem_frag_01", "mem_frag_02", "mem_frag_03"]:
        assert items_map[src_id].status == "consolidated"
        assert items_map[src_id].subsumed_by_id == new_item.memory_id


def test_audit_suite_end_to_end_report() -> None:
    suite = AutoMemoryStalenessAndConsolidationAuditSuite()
    now_str = "2026-10-10T12:00:00Z"

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / "vite.config.ts").write_text("export default {}", encoding="utf-8")

        # 1. Register fresh memory
        suite.register_memory(
            MemoryItemProfile(
                memory_id="mem_1",
                content="Bundler is Vite 6",
                category="tooling",
                created_at="2026-10-10T11:00:00Z",
                referenced_paths=["vite.config.ts"],
            )
        )

        # 2. Register aged memory (60 days old)
        suite.register_memory(
            MemoryItemProfile(
                memory_id="mem_2",
                content="Legacy build flag enabled",
                category="tooling",
                created_at="2026-08-11T12:00:00Z",
                referenced_paths=["vite.config.ts"],
            )
        )

        # 3. Register invalidated memory (non-existent file)
        suite.register_memory(
            MemoryItemProfile(
                memory_id="mem_3",
                content="Webpack externals configured",
                category="tooling",
                created_at="2026-10-10T10:00:00Z",
                referenced_paths=["webpack.config.js"],
            )
        )

        # Run report
        report: MemoryAuditReport = suite.generate_audit_report(
            workspace_dir=tmp_dir, now_iso=now_str
        )

        assert report.total_items == 3
        assert report.invalidated_items == 1
        assert len(report.invalidated_results) == 1
        assert report.invalidated_results[0].memory_id == "mem_3"

        # Proposals generated for category tooling
        assert len(report.consolidation_proposals) >= 1

        # Apply proposal
        prop_id = report.consolidation_proposals[0].proposal_id
        cons_item = suite.apply_consolidation(prop_id, now_iso=now_str)
        assert cons_item is not None
        assert cons_item.status == "active"


def test_archive_memories() -> None:
    suite = AutoMemoryStalenessAndConsolidationAuditSuite()
    suite.register_memory(
        MemoryItemProfile(
            memory_id="mem_arch_01",
            content="Old temp note",
            status="stale",
        )
    )

    archived = suite.archive_memories(["mem_arch_01"])
    assert archived == ["mem_arch_01"]

    it = suite.get_memory("mem_arch_01")
    assert it is not None
    assert it.status == "archived"

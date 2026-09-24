"""Tests for Wiki Frontmatter alias resolution, Chinese Unicode mention extraction, and line anchors."""

from pathlib import Path
import tempfile
import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


@pytest.mark.asyncio
async def test_frontmatter_alias_resolution_and_chinese_anchor() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        structure = WikiStructure(base)
        structure.ensure_structure()
        config = WikiConfig(enable_hybrid_search=False)
        indexer = WikiIndexer(structure, config)

        # 1. Create a concept with frontmatter aliases
        concept_path = structure.get_concept_file_path("hua-chuang-semiconductor")
        concept_content = """---
title: 华创半导体采购规范
type: concept
aliases:
  - 华创
  - 华创微
---
# 华创半导体
这是核心概念文档。
"""
        concept_path.write_text(concept_content, encoding="utf-8")

        # 2. Test alias resolution via WikiStructure
        resolved_path = structure.resolve_alias_file_path("华创")
        assert resolved_path is not None
        assert resolved_path.name == "hua-chuang-semiconductor.md"

        resolved_path_2 = structure.resolve_alias_file_path("华创微.md")
        assert resolved_path_2 is not None
        assert resolved_path_2.name == "hua-chuang-semiconductor.md"

        # 3. Create a deliverable document referencing the concept via Chinese plain text mention
        deliverable_path = structure.get_deliverable_file_path("meeting-minutes.md")
        deliverable_content = """# 项目例会纪要

## 议程概述
团队通报了本季度供应链关键进展。

## 采购审核机制
根据华创最新规定，所有物料需要提前三个工作日审批。

## 后续排期
下周安排供应商现场走访。
"""
        deliverable_path.write_text(deliverable_content, encoding="utf-8")

        # 4. Verify graph_store._find_asset_path resolves via alias
        graph_store = indexer.graph_store
        found_asset = graph_store._find_asset_path("华创")
        assert found_asset is not None
        assert found_asset == concept_path

        # 5. Verify Chinese mention extraction without spaces, with line number and heading
        mention_rec = graph_store._extract_mention_record(deliverable_path, "华创")
        assert mention_rec is not None
        snippet, line_no, heading = mention_rec
        assert "根据华创最新规定" in snippet
        assert line_no == 7  # 7th line in deliverable_content
        assert heading == "采购审核机制"

        # 6. Verify single-character safeguard: "华" should not trigger greedy plain text scan
        single_char_rec = graph_store._extract_mention_record(deliverable_path, "华")
        assert single_char_rec is None

        # 7. Index both documents to test backlinks integration
        await indexer.upsert("hua-chuang-semiconductor", concept_content)
        # Manually create an edge from meeting-minutes to hua-chuang-semiconductor
        with graph_store._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO wiki_edges (source, target, weight) VALUES (?, ?, ?)",
                ("meeting-minutes", "华创", 1.0),
            )
            conn.commit()

        links = graph_store.get_concept_links("华创")
        assert len(links["backlinks"]) == 1
        bl = links["backlinks"][0]
        assert bl["name"] == "meeting-minutes"
        assert bl["exists"] is True
        assert "根据华创最新规定" in bl["context_snippet"]
        assert bl["line_number"] == 7
        assert bl["heading"] == "采购审核机制"

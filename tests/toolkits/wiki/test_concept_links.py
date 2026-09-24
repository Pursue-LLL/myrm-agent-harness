"""Tests for bidirectional concept links, incoming edges, and anchor parsing in WikiGraphStore."""

import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


@pytest.mark.asyncio
async def test_incoming_edges_and_concept_links() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        structure = WikiStructure(base)
        structure.ensure_structure()
        config = WikiConfig(enable_hybrid_search=False)
        indexer = WikiIndexer(structure, config)

        # Create doc A which references B and C with wikilinks, including an anchor
        doc_a_path = structure.get_concept_file_path("doc-a")
        content_a = "# Doc A\n\nHere we reference [[doc-b#heading|Alias B]] and also [[doc-c]].\n"
        doc_a_path.write_text(content_a, encoding="utf-8")

        # Create doc B which references C
        doc_b_path = structure.get_concept_file_path("doc-b")
        content_b = "# Doc B\n\nThis is document B referencing [[doc-c]].\n"
        doc_b_path.write_text(content_b, encoding="utf-8")

        # Create doc C
        doc_c_path = structure.get_concept_file_path("doc-c")
        content_c = "# Doc C\n\nTarget document with no outgoing links.\n"
        doc_c_path.write_text(content_c, encoding="utf-8")

        # Index all via upsert
        await indexer.upsert("doc-a", content_a)
        await indexer.upsert("doc-b", content_b)
        await indexer.upsert("doc-c", content_c)

        # 1. Verify outgoing edges of doc-a
        out_a = dict(indexer.get_outgoing_edges("doc-a"))
        assert "doc-b" in out_a
        assert "doc-c" in out_a

        # 2. Verify incoming edges of doc-c (both doc-a and doc-b reference doc-c)
        inc_c = dict(indexer.get_incoming_edges("doc-c"))
        assert "doc-a" in inc_c
        assert "doc-b" in inc_c

        # 3. Verify get_concept_links for doc-c
        links_c = indexer.get_concept_links("doc-c")
        assert links_c["concept_name"] == "doc-c"
        assert len(links_c["outlinks"]) == 0
        assert len(links_c["backlinks"]) == 2

        # Verify context snippet, line_number, and heading were extracted
        backlink_by_name = {b["name"]: b for b in links_c["backlinks"]}
        assert set(backlink_by_name.keys()) == {"doc-a", "doc-b"}

        b_a = backlink_by_name["doc-a"]
        assert b_a["exists"] is True
        assert b_a["context_snippet"] is not None
        assert "doc-c" in b_a["context_snippet"].lower()
        assert b_a["line_number"] == 3
        assert b_a["heading"] == "Doc A"

        b_b = backlink_by_name["doc-b"]
        assert b_b["exists"] is True
        assert b_b["context_snippet"] is not None
        assert "doc-c" in b_b["context_snippet"].lower()
        assert b_b["line_number"] == 3
        assert b_b["heading"] == "Doc B"


def test_extract_mention_record_edge_cases() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        structure = WikiStructure(base)
        structure.ensure_structure()
        config = WikiConfig(enable_hybrid_search=False)
        indexer = WikiIndexer(structure, config)
        graph_store = indexer._graph_store

        # 1. Multi-level headers & list item markdown prefix removal
        test_file = base / "test_nested.md"
        test_file.write_text(
            "# Top Section\n\nIntro text.\n\n## Sub Section Alpha\n\n- Nested item referencing [[target-concept]].\n",
            encoding="utf-8",
        )
        record = graph_store._extract_mention_record(test_file, "target-concept")
        assert record is not None
        snippet, line_no, heading = record
        assert snippet == "Nested item referencing [[target-concept]]."
        assert line_no == 7
        assert heading == "Sub Section Alpha"

        # 2. Document without any markdown headings
        no_heading_file = base / "no_heading.md"
        no_heading_file.write_text(
            "First line.\nSecond line discussing [[target-concept]] in plain text.\n",
            encoding="utf-8",
        )
        record_nh = graph_store._extract_mention_record(no_heading_file, "target-concept")
        assert record_nh is not None
        snippet_nh, line_no_nh, heading_nh = record_nh
        assert line_no_nh == 2
        assert heading_nh is None
        assert "target-concept" in snippet_nh

        # 3. Long text snippet truncation with 30/70 char boundaries
        long_line_file = base / "long_line.md"
        prefix_padding = "a" * 80
        suffix_padding = "z" * 120
        long_line_file.write_text(
            f"### Heading Long\n\n{prefix_padding} [[target-concept]] {suffix_padding}\n",
            encoding="utf-8",
        )
        record_long = graph_store._extract_mention_record(long_line_file, "target-concept", max_chars=100)
        assert record_long is not None
        snippet_long, line_no_long, heading_long = record_long
        assert line_no_long == 3
        assert heading_long == "Heading Long"
        assert snippet_long.startswith("...")
        assert snippet_long.endswith("...")
        assert "target-concept" in snippet_long

        # 4. Chinese concept & plain text mention
        zh_file = base / "zh_doc.md"
        zh_file.write_text(
            "## 核心架构设计\n\n本项目在微服务层采用了分布式事务作为核心保障机制。\n",
            encoding="utf-8",
        )
        record_zh = graph_store._extract_mention_record(zh_file, "分布式事务")
        assert record_zh is not None
        snippet_zh, line_no_zh, heading_zh = record_zh
        assert line_no_zh == 3
        assert heading_zh == "核心架构设计"
        assert "分布式事务" in snippet_zh

        # 5. Empty target or missing file returns None
        assert graph_store._extract_mention_record(zh_file, "") is None
        assert graph_store._extract_mention_record(zh_file, ".md") is None
        assert graph_store._extract_mention_record(base / "nonexistent.md", "target") is None


def test_asset_path_resolution_and_snippets() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        structure = WikiStructure(base)
        structure.ensure_structure()
        config = WikiConfig(enable_hybrid_search=False)
        indexer = WikiIndexer(structure, config)
        graph_store = indexer._graph_store

        # 1. Concept path
        concept_path = structure.get_concept_file_path("my-concept")
        concept_path.write_text("# My Concept\n", encoding="utf-8")
        assert graph_store._find_asset_path("my-concept") == concept_path
        assert graph_store._find_asset_path("my-concept.md") == concept_path

        # 2. Deliverable path
        deliv_path = structure.get_deliverable_file_path("summary.md")
        deliv_path.write_text("# Deliverable Summary\n", encoding="utf-8")
        assert graph_store._find_asset_path("summary") == deliv_path

        # 3. Method path
        method_path = structure.get_method_file_path("standard-operating-proc")
        method_path.write_text("# Method\n", encoding="utf-8")
        assert graph_store._find_asset_path("standard-operating-proc") == method_path

        # 4. Claim path
        claim_path = structure.get_claim_file_path("architectural-axiom")
        claim_path.write_text("# Claim\n", encoding="utf-8")
        assert graph_store._find_asset_path("architectural-axiom") == claim_path

        # 5. Frontmatter alias lookup
        aliased_concept = structure.get_concept_file_path("original-concept")
        aliased_concept.write_text(
            "---\naliases: [\"cool-alias\"]\n---\n# Original\n",
            encoding="utf-8",
        )
        structure.invalidate_alias_cache()
        assert graph_store._find_asset_path("cool-alias") == aliased_concept

        # 6. Non-existent asset
        assert graph_store._find_asset_path("non-existent-xyz") is None

        # 7. _extract_mention_snippet helper
        test_file = base / "snippet_test.md"
        test_file.write_text("Context about [[my-concept]] in here.\n", encoding="utf-8")
        snip = graph_store._extract_mention_snippet(test_file, "my-concept")
        assert snip is not None
        assert "[[my-concept]]" in snip
        assert graph_store._extract_mention_snippet(base / "none.md", "my-concept") is None


@pytest.mark.asyncio
async def test_knowledge_graph_full_and_insights() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        structure = WikiStructure(base)
        structure.ensure_structure()
        config = WikiConfig(enable_hybrid_search=False)
        indexer = WikiIndexer(structure, config)
        graph_store = indexer._graph_store

        # Populate two concepts with cross-references
        doc_a = structure.get_concept_file_path("node-a")
        doc_b = structure.get_concept_file_path("node-b")
        content_a = "# Node A\nReferences [[node-b]].\n"
        content_b = "# Node B\nReferences [[node-a]].\n"
        doc_a.write_text(content_a, encoding="utf-8")
        doc_b.write_text(content_b, encoding="utf-8")
        await indexer.upsert("node-a", content_a)
        await indexer.upsert("node-b", content_b)

        # 1. Full knowledge graph (center_node=None)
        full_graph = graph_store.get_knowledge_graph(center_node=None, limit=50)
        assert len(full_graph["nodes"]) >= 2
        assert len(full_graph["edges"]) >= 1

        # 2. Outlinks verification in get_concept_links
        links_a = graph_store.get_concept_links("node-a")
        assert len(links_a["outlinks"]) == 1
        assert links_a["outlinks"][0]["name"] == "node-b"
        assert links_a["outlinks"][0]["exists"] is True

        # 3. BFS with limit to trigger limit-break path
        limited_graph = graph_store.get_knowledge_graph(center_node="node-a", depth=2, limit=1)
        assert len(limited_graph["nodes"]) <= 2

        # 4. Graph insights
        insights = graph_store.graph_insights()
        assert isinstance(insights, dict)


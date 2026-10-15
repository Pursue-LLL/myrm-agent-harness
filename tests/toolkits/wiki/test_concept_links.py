"""Tests for bidirectional concept links, incoming edges, and anchor parsing in WikiGraphStore."""

import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.graph_store import MAX_CONCEPT_LINKS
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

        # 2. Verify get_concept_links for doc-c (both doc-a and doc-b reference doc-c)
        links_c = indexer.get_concept_links("doc-c")
        assert links_c["concept_name"] == "doc-c"
        assert len(links_c["outlinks"]) == 0
        assert len(links_c["backlinks"]) == 2

        # Verify context snippet and heading were extracted
        backlink_by_name = {b["name"]: b for b in links_c["backlinks"]}
        assert set(backlink_by_name.keys()) == {"doc-a", "doc-b"}

        b_a = backlink_by_name["doc-a"]
        assert b_a["exists"] is True
        assert b_a["context_snippet"] is not None
        assert "doc-c" in b_a["context_snippet"].lower()
        assert b_a["heading"] == "Doc A"

        b_b = backlink_by_name["doc-b"]
        assert b_b["exists"] is True
        assert b_b["context_snippet"] is not None
        assert "doc-c" in b_b["context_snippet"].lower()
        assert b_b["heading"] == "Doc B"


@pytest.mark.asyncio
async def test_concept_links_payload_carries_only_what_the_panel_reads() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        structure = WikiStructure(Path(tmpdir))
        structure.ensure_structure()
        indexer = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))
        await _write_page(structure, indexer, "hub", "# Hub\n\n## Part\nSee [[leaf]].\n")
        await _write_page(structure, indexer, "leaf", "# Leaf\n\nBack to [[hub]].\n")

        links = indexer.get_concept_links("hub")

    assert set(links) == {"concept_name", "outlinks", "backlinks", "outlinks_has_more", "backlinks_has_more"}
    assert [set(record) for record in links["outlinks"]] == [{"name", "exists"}]
    assert [set(record) for record in links["backlinks"]] == [{"name", "exists", "context_snippet", "heading"}]
    assert links["outlinks_has_more"] is False
    assert links["backlinks_has_more"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("linkers", "expect_more"),
    [(MAX_CONCEPT_LINKS, False), (MAX_CONCEPT_LINKS + 1, True)],
)
async def test_backlinks_report_whether_the_cap_cut_the_list(linkers: int, expect_more: bool) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        structure = WikiStructure(Path(tmpdir))
        structure.ensure_structure()
        indexer = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))
        await _write_page(structure, indexer, "hub", "# Hub\n\nThe hub.\n")
        for i in range(linkers):
            await _write_page(structure, indexer, f"notes/n{i:03d}", f"# N{i}\n\nSee [[hub]].\n")

        links = indexer.get_concept_links("hub")

    assert len(links["backlinks"]) == MAX_CONCEPT_LINKS
    assert links["backlinks_has_more"] is expect_more
    assert links["outlinks_has_more"] is False


@pytest.mark.asyncio
async def test_outlinks_report_the_cap_independently_of_backlinks() -> None:
    targets = "\n".join(f"- [[t{i:03d}]]" for i in range(MAX_CONCEPT_LINKS + 1))
    with tempfile.TemporaryDirectory() as tmpdir:
        structure = WikiStructure(Path(tmpdir))
        structure.ensure_structure()
        indexer = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))
        await _write_page(structure, indexer, "catalog", f"# Catalog\n\n{targets}\n")

        links = indexer.get_concept_links("catalog")

    assert len(links["outlinks"]) == MAX_CONCEPT_LINKS
    assert links["outlinks_has_more"] is True
    assert links["backlinks"] == []
    assert links["backlinks_has_more"] is False


@pytest.mark.asyncio
async def test_capped_backlinks_are_ordered_by_name_and_survive_an_edit() -> None:
    """Every backlink ties on weight, so which 100 are listed must not depend on write order or on re-indexing."""
    names = [f"notes/n{i:03d}" for i in range(MAX_CONCEPT_LINKS + 1)]
    with tempfile.TemporaryDirectory() as tmpdir:
        structure = WikiStructure(Path(tmpdir))
        structure.ensure_structure()
        indexer = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))
        await _write_page(structure, indexer, "hub", "# Hub\n\nThe hub.\n")
        for name in reversed(names):
            await _write_page(structure, indexer, name, "# N\n\nSee [[hub]].\n")

        before = [b["name"] for b in indexer.get_concept_links("hub")["backlinks"]]
        await _write_page(structure, indexer, names[0], "# N\n\nTypo fixed. See [[hub]].\n")
        after = [b["name"] for b in indexer.get_concept_links("hub")["backlinks"]]

    assert before == names[:MAX_CONCEPT_LINKS]
    assert after == before


@pytest.mark.asyncio
async def test_capped_outlinks_are_ordered_by_name_whichever_index_the_planner_scans() -> None:
    targets = [f"t{i:03d}" for i in range(MAX_CONCEPT_LINKS + 1)]
    links = "\n".join(f"- [[{target}]]" for target in reversed(targets))
    with tempfile.TemporaryDirectory() as tmpdir:
        structure = WikiStructure(Path(tmpdir))
        structure.ensure_structure()
        indexer = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))
        # A source-only index makes SQLite read a page's edges in write order instead of the primary key's name order.
        with indexer._get_conn() as conn:
            conn.execute("CREATE INDEX idx_edges_source_only ON wiki_edges(source)")
        await _write_page(structure, indexer, "catalog", f"# Catalog\n\n{links}\n")

        outlinks = [link["name"] for link in indexer.get_concept_links("catalog")["outlinks"]]

    assert outlinks == targets[:MAX_CONCEPT_LINKS]


def test_extract_mention_record_edge_cases() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        structure = WikiStructure(base)
        structure.ensure_structure()
        config = WikiConfig(enable_hybrid_search=False)
        indexer = WikiIndexer(structure, config)
        graph_store = indexer._graph_store

        def mention(path: Path, name: str, max_chars: int = 140) -> tuple[str, str | None] | None:
            return graph_store._extract_mention_record(path, graph_store._target_spellings(name), max_chars)

        # 1. Multi-level headers & list item markdown prefix removal
        test_file = base / "test_nested.md"
        test_file.write_text(
            "# Top Section\n\nIntro text.\n\n## Sub Section Alpha\n\n- Nested item referencing [[target-concept]].\n",
            encoding="utf-8",
        )
        record = mention(test_file, "target-concept")
        assert record is not None
        snippet, heading = record
        assert snippet == "Nested item referencing [[target-concept]]."
        assert heading == "Sub Section Alpha"

        # 2. Document without any markdown headings
        no_heading_file = base / "no_heading.md"
        no_heading_file.write_text(
            "First line.\nSecond line discussing [[target-concept]] in plain text.\n",
            encoding="utf-8",
        )
        record_nh = mention(no_heading_file, "target-concept")
        assert record_nh is not None
        snippet_nh, heading_nh = record_nh
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
        record_long = mention(long_line_file, "target-concept", max_chars=100)
        assert record_long is not None
        snippet_long, heading_long = record_long
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
        record_zh = mention(zh_file, "分布式事务")
        assert record_zh is not None
        snippet_zh, heading_zh = record_zh
        assert heading_zh == "核心架构设计"
        assert "分布式事务" in snippet_zh

        # 5. Empty target or missing file returns None
        assert mention(zh_file, "") is None
        assert mention(zh_file, ".md") is None
        assert mention(base / "nonexistent.md", "target") is None


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
            '---\naliases: ["cool-alias"]\n---\n# Original\n',
            encoding="utf-8",
        )
        structure.invalidate_alias_cache()
        assert graph_store._find_asset_path("cool-alias") == aliased_concept

        # 6. Non-existent asset
        assert graph_store._find_asset_path("non-existent-xyz") is None

        # 7. A markdown link naming the page by its key is a mention too
        test_file = base / "snippet_test.md"
        test_file.write_text("Context about [the concept](my-concept.md) in here.\n", encoding="utf-8")
        record = graph_store._extract_mention_record(test_file, graph_store._target_spellings("my-concept"))
        assert record is not None
        assert record[0] == "Context about [the concept](my-concept.md) in here."
        assert (
            graph_store._extract_mention_record(base / "none.md", graph_store._target_spellings("my-concept")) is None
        )


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


async def _write_page(structure: WikiStructure, indexer: WikiIndexer, name: str, content: str) -> None:
    path = structure.get_concept_file_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    await indexer.upsert(name, content)


@pytest.mark.asyncio
async def test_backlink_context_for_every_spelling_the_resolver_accepts() -> None:
    claims = "".join(
        f"  - id: c{i}\n    text: Quoted fact {i} with exact figures and dates.\n    status: supported\n"
        for i in range(1, 40)
    )
    target = (
        "---\ntype: concept\ntitle: Five Layer View\ncanonical_id: arch-five-layer\naliases: [5LA]\n"
        f"claims:\n{claims}---\n## Compiled Truth\nLayers.\n"
    )
    assert target.index("## Compiled Truth") > 2048, "aliases must sit beyond a 2 KB prefix of the page"

    spellings = {
        "by-key": "[[knowledge/arch/five-layer]]",
        "by-key-case-fragment-label": "[[Knowledge/Arch/Five-Layer#Layers|the layers]]",
        "by-file-name": "[[five-layer]]",
        "by-alias": "[[5LA]]",
        "by-title": "[[Five Layer View]]",
        "by-canonical-id": "[[arch-five-layer]]",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        structure = WikiStructure(Path(tmpdir))
        structure.ensure_structure()
        indexer = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))
        await _write_page(structure, indexer, "knowledge/arch/five-layer", target)
        for label, link in spellings.items():
            note = f"# Notes\nRelated: [[unrelated-page]].\n\n## Layers\nSee {link} for the layered view.\n"
            await _write_page(structure, indexer, f"projects/src/{label}", note)

        backlinks = {b["name"]: b for b in indexer.get_concept_links("knowledge/arch/five-layer")["backlinks"]}

    assert set(backlinks) == {f"projects/src/{label}" for label in spellings}
    for label, link in spellings.items():
        record = backlinks[f"projects/src/{label}"]
        assert record["context_snippet"] == f"See {link} for the layered view.", label
        assert record["heading"] == "Layers", label


@pytest.mark.asyncio
async def test_generic_file_name_counts_only_when_written_as_a_link() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        structure = WikiStructure(Path(tmpdir))
        structure.ensure_structure()
        indexer = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))
        await _write_page(structure, indexer, "knowledge/x/overview", "# Overview\nThe page.\n")
        note = "# Notes\nA short overview of the topic.\n\n## Details\nSee [[Overview]] for details.\n"
        await _write_page(structure, indexer, "projects/notes", note)

        record = indexer.get_concept_links("knowledge/x/overview")["backlinks"][0]

    assert record["name"] == "projects/notes"
    assert record["context_snippet"] == "See [[Overview]] for details."
    assert record["heading"] == "Details"

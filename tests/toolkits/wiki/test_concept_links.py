"""Tests for bidirectional concept links, incoming edges, and anchor parsing in WikiGraphStore."""

from pathlib import Path
import tempfile
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

        # Verify context snippet was extracted
        backlink_names = {b["name"] for b in links_c["backlinks"]}
        assert backlink_names == {"doc-a", "doc-b"}
        for b in links_c["backlinks"]:
            assert b["exists"] is True
            assert b["context_snippet"] is not None
            assert "doc-c" in b["context_snippet"].lower()

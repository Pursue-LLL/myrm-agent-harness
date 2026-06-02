import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


@pytest.fixture
def federated_structures(tmp_path):
    """Create local structure and a public mock structure."""
    local_dir = tmp_path / "local"
    pub_dir = tmp_path / "public"

    # Init public
    pub_structure = WikiStructure(pub_dir)
    pub_structure.ensure_structure()
    pub_indexer = WikiIndexer(pub_structure, WikiConfig(enable_hybrid_search=False))

    # Init local with public mount
    local_structure = WikiStructure(local_dir, public_dirs=[pub_dir])
    local_structure.ensure_structure()
    local_indexer = WikiIndexer(local_structure, WikiConfig(enable_hybrid_search=False))

    return pub_indexer, local_indexer


@pytest.mark.asyncio
async def test_federated_indexer(federated_structures):
    pub_indexer, local_indexer = federated_structures

    # 1. Upsert public data
    await pub_indexer.upsert("Public Concept", "## Compiled Truth\nPublic content test")
    pub_indexer.upsert_edges("Public Concept", ["Public Target", "Local Concept"])

    # 2. Upsert local data
    await local_indexer.upsert("Local Concept", "## Compiled Truth\nLocal content test")
    local_indexer.upsert_edges("Local Concept", ["Public Concept"])

    # Test federated get_truth
    assert "Public content" in local_indexer.get_truth("Public Concept")
    assert "Local content" in local_indexer.get_truth("Local Concept")

    # Test federated search
    results = await local_indexer.search("test")
    names = [r[0] for r in results]
    assert "Public Concept" in names
    assert "Local Concept" in names

    # Test federated get_knowledge_graph global
    graph = local_indexer.get_knowledge_graph()
    node_ids = [n["id"] for n in graph["nodes"]]
    assert "Public Concept" in node_ids
    assert "Local Concept" in node_ids

    # Test progressive BFS get_knowledge_graph (center=Local Concept, depth=1)
    graph_bfs = local_indexer.get_knowledge_graph(center_node="Local Concept", depth=1, limit=100)
    node_ids_bfs = [n["id"] for n in graph_bfs["nodes"]]
    assert "Local Concept" in node_ids_bfs
    assert "Public Concept" in node_ids_bfs

    # Edges deduplication should work
    edges_bfs = graph_bfs["edges"]
    assert any(e["source"] == "Local Concept" and e["target"] == "Public Concept" for e in edges_bfs)


@pytest.mark.asyncio
async def test_indexer_delete_and_edges(federated_structures):
    _pub_indexer, local_indexer = federated_structures

    await local_indexer.upsert("Node A", "## Compiled Truth\nA")
    await local_indexer.upsert("Node B", "## Compiled Truth\nB")
    local_indexer.upsert_edges("Node A", ["Node B", "Node C"])

    graph = local_indexer.get_knowledge_graph()
    assert any(e["source"] == "Node A" and e["target"] == "Node B" for e in graph["edges"])

    await local_indexer.delete("Node A")
    graph_after = local_indexer.get_knowledge_graph()
    assert not any(e["source"] == "Node A" for e in graph_after["edges"])


@pytest.mark.asyncio
async def test_structure_federated_methods(tmp_path):
    # Test list_raw_files excludes public, but list_concepts includes public
    local_dir = tmp_path / "local"
    pub_dir = tmp_path / "public"

    local_s = WikiStructure(local_dir, public_dirs=[pub_dir])
    local_s.ensure_structure()

    pub_s = WikiStructure(pub_dir)
    pub_s.ensure_structure()

    (pub_s.raw_dir / "pub.md").touch()
    (local_s.raw_dir / "loc.md").touch()

    raws = local_s.list_raw_files()
    assert len(raws) == 1
    assert "loc.md" in raws[0].name

    (pub_s.concepts_dir / "pub-concept.md").touch()
    (local_s.concepts_dir / "loc-concept.md").touch()

    concepts = local_s.list_concepts()
    assert len(concepts) == 2

    res = local_s.resolve_concept_file_path("pub-concept")
    assert res and "public" in str(res)

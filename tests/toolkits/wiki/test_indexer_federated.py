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


@pytest.mark.asyncio
async def test_federated_offline_and_corrupt_resilience(tmp_path):
    # Test non-existent and unreadable public dirs do not crash search
    local_dir = tmp_path / "local"
    missing_dir = tmp_path / "missing_dir_xyz"
    corrupt_dir = tmp_path / "corrupt_dir"
    corrupt_dir.mkdir(parents=True, exist_ok=True)
    # Put a non-sqlite file as .wiki_index.db to simulate corruption
    (corrupt_dir / ".wiki_index.db").write_text("not a valid sqlite db")

    local_s = WikiStructure(local_dir, public_dirs=[missing_dir, corrupt_dir])
    local_s.ensure_structure()

    local_indexer = WikiIndexer(local_s)
    await local_indexer.upsert("Local Resilience", "## Compiled Truth\nHealthy content")

    # Search should succeed and not raise SQLite OperationalError
    res = await local_indexer.search("Healthy", limit=5)
    assert len(res) == 1
    assert res[0][0] == "Local Resilience"

    # get_truth should also succeed safely without SQLite OperationalError
    truth = local_indexer.get_truth("Local Resilience")
    assert truth is not None and "Healthy content" in truth

    # Graph retrieval should also succeed safely
    graph = local_indexer.get_knowledge_graph()
    assert any(n["id"] == "Local Resilience" for n in graph["nodes"])


@pytest.mark.asyncio
async def test_federated_multi_source_labels_and_citations(tmp_path):
    local_dir = tmp_path / "local"
    kb1_dir = tmp_path / "kb1"
    kb2_dir = tmp_path / "kb2"

    kb1_s = WikiStructure(kb1_dir)
    kb1_s.ensure_structure()
    kb1_indexer = WikiIndexer(kb1_s, WikiConfig(enable_hybrid_search=False))
    await kb1_indexer.upsert("Arch Spec", "## Compiled Truth\nMicroservices architecture standard")

    kb2_s = WikiStructure(kb2_dir)
    kb2_s.ensure_structure()
    kb2_indexer = WikiIndexer(kb2_s, WikiConfig(enable_hybrid_search=False))
    await kb2_indexer.upsert("Sec Policy", "## Compiled Truth\nZero trust network security rules")

    # Local mounts both with labels
    labels = {
        str(kb1_dir.resolve()): "Enterprise Architecture",
        str(kb2_dir.resolve()): "Security Guidelines",
    }
    local_s = WikiStructure(local_dir, public_dirs=[kb1_dir, kb2_dir], public_dir_labels=labels)
    local_s.ensure_structure()
    local_indexer = WikiIndexer(local_s, WikiConfig(enable_hybrid_search=False))

    # Cross-source hybrid/fts search returns matches across all mounted bases
    res_arch = await local_indexer.search("architecture")
    assert len(res_arch) == 1
    assert res_arch[0][0] == "Arch Spec"

    res_sec = await local_indexer.search("security")
    assert len(res_sec) == 1
    assert res_sec[0][0] == "Sec Policy"

    # Verify truth retrieval from federated attachments
    truth_arch = local_indexer.get_truth("Arch Spec")
    assert truth_arch is not None and "Microservices" in truth_arch

    truth_sec = local_indexer.get_truth("Sec Policy")
    assert truth_sec is not None and "Zero trust" in truth_sec

    # Verify knowledge graph merges all sources
    graph = local_indexer.get_knowledge_graph()
    nodes = {n["id"] for n in graph["nodes"]}
    assert "Arch Spec" in nodes
    assert "Sec Policy" in nodes


@pytest.mark.asyncio
async def test_federated_indexer_handles_empty_or_uninitialized_database_gracefully(tmp_path):
    """Mounting an empty SQLite DB without wiki_fts must not crash federated search or graph."""
    import sqlite3

    local_dir = tmp_path / "local_clean"
    empty_kb_dir = tmp_path / "empty_kb"
    empty_kb_dir.mkdir(parents=True, exist_ok=True)

    # Create an empty sqlite database file without wiki_fts or wiki_edges tables
    empty_db_path = empty_kb_dir / ".wiki_index.db"
    conn = sqlite3.connect(str(empty_db_path))
    conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    local_s = WikiStructure(local_dir, public_dirs=[empty_kb_dir])
    local_s.ensure_structure()
    local_indexer = WikiIndexer(local_s, WikiConfig(enable_hybrid_search=False))

    await local_indexer.upsert("Local Knowledge", "## Compiled Truth\nLocal production knowledge")

    # 1. Search must succeed without OperationalError: no such table
    results = await local_indexer.search("production")
    assert len(results) >= 1
    assert results[0][0] == "Local Knowledge"

    # 2. get_truth must succeed
    truth = local_indexer.get_truth("Local Knowledge")
    assert truth is not None and "Local production knowledge" in truth

    # 3. get_knowledge_graph must succeed
    graph = local_indexer.get_knowledge_graph()
    node_ids = {n["id"] for n in graph["nodes"]}
    assert "Local Knowledge" in node_ids


@pytest.mark.asyncio
async def test_federated_indexer_more_than_six_public_dirs_clamped(tmp_path):
    """Mounting >6 public directories clamps to first 6 to satisfy SQLite ATTACH limits."""
    local_dir = tmp_path / "local_clamp"
    dirs = []
    for i in range(10):
        d = tmp_path / f"kb_{i}"
        s = WikiStructure(d)
        s.ensure_structure()
        idx = WikiIndexer(s, WikiConfig(enable_hybrid_search=False))
        await idx.upsert(f"Concept_{i}", f"## Compiled Truth\nContent from base {i}")
        dirs.append(d)

    local_s = WikiStructure(local_dir, public_dirs=dirs)
    local_s.ensure_structure()
    local_idx = WikiIndexer(local_s, WikiConfig(enable_hybrid_search=False))

    # Search should query up to first 6 without error
    res = await local_idx.search("Content", limit=20)
    matched_names = {r[0] for r in res}
    # Concepts 0 to 5 should be searchable
    assert "Concept_0" in matched_names
    assert "Concept_5" in matched_names
    # Concept 6 to 9 clamped by 6 attachments limit
    assert "Concept_7" not in matched_names





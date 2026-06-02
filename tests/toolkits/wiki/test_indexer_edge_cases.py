from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer, _tokenize_for_fts


@pytest.fixture
def wiki_structure(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_vector_store():
    store = AsyncMock()
    store.collection_exists.return_value = False
    store.create_collection = AsyncMock()
    store.ensure_collection = AsyncMock()
    store.upsert = AsyncMock()
    store.search = AsyncMock()
    return store


@pytest.fixture
def mock_embedding():
    embedding = AsyncMock()
    embedding.embed.return_value = [0.1, 0.2, 0.3]
    return embedding


@pytest.mark.asyncio
async def test_indexer_graceful_degradation_on_vector_search_failure(wiki_structure, mock_vector_store, mock_embedding):
    config = WikiConfig(enable_hybrid_search=True)
    mock_vector_store.search.side_effect = Exception("Simulated Vector DB Failure")

    indexer = WikiIndexer(wiki_structure, config, vector_store=mock_vector_store, embedding=mock_embedding)
    await indexer.upsert("Test Concept", "## Compiled Truth\nTest knowledge.")

    # Vector search throws exception, should degrade to FTS5
    results = await indexer.search("Test")

    assert len(results) == 1
    assert results[0][0] == "Test Concept"
    mock_vector_store.search.assert_awaited()


@pytest.mark.asyncio
async def test_indexer_graceful_degradation_on_vector_upsert_failure(wiki_structure, mock_vector_store, mock_embedding):
    config = WikiConfig(enable_hybrid_search=True)
    mock_vector_store.upsert.side_effect = Exception("Simulated Vector DB Failure")

    indexer = WikiIndexer(wiki_structure, config, vector_store=mock_vector_store, embedding=mock_embedding)

    # Should not raise exception
    await indexer.upsert("Test Concept", "## Compiled Truth\nTest knowledge.")

    # Should still be in FTS5
    truth = indexer.get_truth("Test Concept")
    assert "Test knowledge." in truth


@pytest.mark.asyncio
async def test_indexer_empty_query(wiki_structure, mock_vector_store, mock_embedding):
    config = WikiConfig(enable_hybrid_search=True)
    indexer = WikiIndexer(wiki_structure, config, vector_store=mock_vector_store, embedding=mock_embedding)

    await indexer.upsert("Test Concept", "## Compiled Truth\nTest knowledge.")

    # Empty query should return empty list without calling vector search
    results = await indexer.search("   ")
    assert len(results) == 0
    mock_vector_store.search.assert_not_called()


def test_indexer_extract_truth_fallback():
    # Test extract_truth when there's no Compiled Truth section
    content = "# Title\n\nJust some random content without sections."
    truth = WikiIndexer._extract_truth(content)
    assert truth == content


def test_indexer_extract_truth_with_yaml():
    content = "---\ntags: [a]\n---\n# Title\n\n## Compiled Truth\nReal truth here.\n## Timeline\nIgnored."
    truth = WikiIndexer._extract_truth(content)
    assert "---\ntags: [a]\n---\n" in truth
    assert "Real truth here." in truth
    assert "Ignored." not in truth


def test_extract_and_upsert_edges_markdown_links(wiki_structure):
    """extract_and_upsert_edges parses standard [text](link.md) and [[Wikilinks]]."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    content = (
        "See [NeuralNet](NeuralNet.md) and also [[Transformer|GPT]] for details.\n"
        "More at [[Attention]]."
    )
    indexer.extract_and_upsert_edges("DeepLearning", content)

    with indexer._get_conn() as conn:
        cursor = conn.execute("SELECT target, weight FROM wiki_edges WHERE source = ?", ("DeepLearning",))
        edges = {row["target"]: row["weight"] for row in cursor.fetchall()}

    assert "NeuralNet" in edges
    assert "Transformer" in edges
    assert "Attention" in edges
    assert all(w >= 3.0 for w in edges.values())


@pytest.mark.asyncio
async def test_delete_removes_fts_and_edges(wiki_structure):
    """delete() removes concept from FTS5 and edges."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert("ToDelete", "## Compiled Truth\nSome knowledge.")
    indexer.upsert_edges("ToDelete", ["Other"])

    results_before = await indexer.search("knowledge")
    assert len(results_before) == 1

    await indexer.delete("ToDelete")

    results_after = await indexer.search("knowledge")
    assert len(results_after) == 0

    with indexer._get_conn() as conn:
        cursor = conn.execute("SELECT * FROM wiki_edges WHERE source = ? OR target = ?", ("ToDelete", "ToDelete"))
        assert cursor.fetchone() is None


@pytest.mark.asyncio
async def test_get_knowledge_graph(wiki_structure):
    """get_knowledge_graph returns nodes and edges with val and weight."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert("NodeA", "## Compiled Truth\nNodeA.")
    await indexer.upsert("NodeB", "## Compiled Truth\nNodeB.")
    indexer.upsert_edges("NodeA", ["NodeB"])

    graph = indexer.get_knowledge_graph()
    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) >= 1

    node_ids = {n["id"] for n in graph["nodes"]}
    assert "NodeA" in node_ids
    assert "NodeB" in node_ids

    for edge in graph["edges"]:
        assert "weight" in edge
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids

    node_a = next(n for n in graph["nodes"] if n["id"] == "NodeA")
    assert "val" in node_a
    assert node_a["val"] >= 1


@pytest.mark.asyncio
async def test_graph_insights_with_data(wiki_structure):
    """graph_insights returns communities, gaps, and unexpected connections."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    for name in ("A", "B", "C", "D"):
        await indexer.upsert(name, f"## Compiled Truth\n{name} content.")

    indexer.upsert_edges("A", ["B"])
    indexer.upsert_edges("B", ["C"])
    # D is isolated: knowledge gap

    insights = indexer.graph_insights()
    assert "communities" in insights
    assert "knowledge_gaps" in insights
    assert "unexpected_connections" in insights

    gap_names = [g["node"] for g in insights["knowledge_gaps"]]
    assert "D" in gap_names


def test_edge_weight_calculation(wiki_structure):
    """_calculate_edge_weight computes multi-dimensional weight."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    indexer.upsert_edges("X", ["Y"])
    indexer.upsert_edges("Y", ["Z"])
    indexer.upsert_edges("X", ["Z"])

    with indexer._get_conn() as conn:
        weight = indexer._calculate_edge_weight(conn, "X", "Z", source_files=["file1.md"])

    assert weight >= 3.0


# --- CJK Tokenizer Tests ---


def test_tokenize_for_fts_pure_english():
    """Pure English query produces quoted tokens."""
    result = _tokenize_for_fts("machine learning algorithm")
    assert '"machine"' in result
    assert '"learning"' in result
    assert '"algorithm"' in result


def test_tokenize_for_fts_pure_cjk():
    """CJK text is split into bigrams."""
    result = _tokenize_for_fts("深度学习")
    assert '"深度"' in result
    assert '"度学"' in result
    assert '"学习"' in result


def test_tokenize_for_fts_mixed():
    """Mixed CJK and English produces both types of tokens."""
    result = _tokenize_for_fts("LLM架构设计")
    assert '"LLM"' in result
    assert '"架构"' in result
    assert '"构设"' in result
    assert '"设计"' in result


def test_tokenize_for_fts_single_cjk_char():
    """Single CJK character is quoted directly (no bigram possible)."""
    result = _tokenize_for_fts("AI是")
    assert '"AI"' in result
    assert '"是"' in result


def test_tokenize_for_fts_empty():
    """Empty input returns empty string."""
    assert _tokenize_for_fts("") == ""
    assert _tokenize_for_fts("   ") == ""


def test_tokenize_for_fts_stop_words_removed():
    """Common English stop words are excluded."""
    result = _tokenize_for_fts("the is a an of")
    assert result.strip() == ""


# --- BFS Graph Tests ---


@pytest.mark.asyncio
async def test_get_knowledge_graph_bfs(wiki_structure):
    """get_knowledge_graph with center_node uses BFS traversal."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert("Center", "## Compiled Truth\nCenter node.")
    await indexer.upsert("Neighbor1", "## Compiled Truth\nNeighbor 1.")
    await indexer.upsert("Neighbor2", "## Compiled Truth\nNeighbor 2.")
    await indexer.upsert("Far", "## Compiled Truth\nFar away node.")

    indexer.upsert_edges("Center", ["Neighbor1", "Neighbor2"])
    indexer.upsert_edges("Neighbor1", ["Far"])

    graph_d1 = indexer.get_knowledge_graph(center_node="Center", depth=1)
    node_ids_d1 = {n["id"] for n in graph_d1["nodes"]}
    assert "Center" in node_ids_d1
    assert "Neighbor1" in node_ids_d1
    assert "Neighbor2" in node_ids_d1
    assert "Far" not in node_ids_d1

    graph_d2 = indexer.get_knowledge_graph(center_node="Center", depth=2)
    node_ids_d2 = {n["id"] for n in graph_d2["nodes"]}
    assert "Far" in node_ids_d2


@pytest.mark.asyncio
async def test_get_knowledge_graph_bfs_nonexistent_center(wiki_structure):
    """BFS with a nonexistent center_node returns empty graph."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    graph = indexer.get_knowledge_graph(center_node="DoesNotExist", depth=1)
    assert len(graph["nodes"]) == 0
    assert len(graph["edges"]) == 0

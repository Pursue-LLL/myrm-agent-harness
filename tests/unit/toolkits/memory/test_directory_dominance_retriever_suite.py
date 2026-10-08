"""[POS]: tests/unit/toolkits/memory/test_directory_dominance_retriever_suite.py
[INPUT]: Hierarchy nodes, dominance ratio configurations, and simulated test queries.
[OUTPUT]: Pytest test cases verifying directory dominance ratio thresholds, sibling bundling, and convergence.
"""


from myrm_agent_harness.toolkits.memory.directory_dominance import (
    DirectoryDominanceConfig,
    DominanceDecisionKind,
    HierarchicalDirectoryDominanceRetriever,
    HierarchicalNode,
    HierarchyNodeType,
)


def test_evaluate_dominance_ratio_thresholds() -> None:
    """Verify that DIRECTORY_DOMINANCE_RATIO = 1.2 precisely governs dominance decisions."""
    retriever = HierarchicalDirectoryDominanceRetriever(
        config=DirectoryDominanceConfig(dominance_ratio=1.2)
    )

    dir_node = HierarchicalNode(
        uri="context://resources/auth/",
        node_type=HierarchyNodeType.DIRECTORY,
        name="auth",
        score=0.90,
    )

    child_1 = HierarchicalNode(
        uri="context://resources/auth/oauth.py",
        node_type=HierarchyNodeType.FILE,
        name="oauth.py",
        parent_uri="context://resources/auth/",
        score=0.70,
    )
    child_2 = HierarchicalNode(
        uri="context://resources/auth/jwt.py",
        node_type=HierarchyNodeType.FILE,
        name="jwt.py",
        parent_uri="context://resources/auth/",
        score=0.65,
    )

    # 1. 0.90 >= 0.70 * 1.2 (= 0.84) -> Directory Dominant
    decision_dominant = retriever.evaluate_dominance(dir_node, [child_1, child_2])
    assert decision_dominant == DominanceDecisionKind.DIRECTORY_DOMINANT

    # 2. dir_score = 0.75, max_child = 0.70 (0.75 < 0.84) -> Balanced
    dir_node_balanced = dir_node.model_copy(update={"score": 0.75})
    decision_balanced = retriever.evaluate_dominance(dir_node_balanced, [child_1, child_2])
    assert decision_balanced == DominanceDecisionKind.BALANCED

    # 3. dir_score = 0.50, max_child = 0.85 -> Leaf Specific
    child_strong = child_1.model_copy(update={"score": 0.85})
    dir_node_weak = dir_node.model_copy(update={"score": 0.50})
    decision_leaf = retriever.evaluate_dominance(dir_node_weak, [child_strong, child_2])
    assert decision_leaf == DominanceDecisionKind.LEAF_SPECIFIC


def test_sibling_context_bundling() -> None:
    """Verify that localized leaf hits bundle sibling summaries and parent context."""
    retriever = HierarchicalDirectoryDominanceRetriever(
        config=DirectoryDominanceConfig(
            dominance_ratio=1.2,
            max_siblings_per_hit=2,
            include_parent_context=True,
        )
    )

    dir_node = HierarchicalNode(
        uri="context://resources/auth/",
        node_type=HierarchyNodeType.DIRECTORY,
        name="auth",
        abstract="Authentication and authorization subsystem architecture.",
        score=0.40,
    )
    hit_node = HierarchicalNode(
        uri="context://resources/auth/oauth.py",
        node_type=HierarchyNodeType.FILE,
        name="oauth.py",
        parent_uri="context://resources/auth/",
        abstract="OAuth2 Authorization Code Grant flow handler.",
        content="def handle_oauth_flow(): ...",
        score=0.92,
    )
    sibling_1 = HierarchicalNode(
        uri="context://resources/auth/jwt.py",
        node_type=HierarchyNodeType.FILE,
        name="jwt.py",
        parent_uri="context://resources/auth/",
        abstract="JSON Web Token issuance and signature verification.",
        score=0.60,
    )
    sibling_2 = HierarchicalNode(
        uri="context://resources/auth/session.py",
        node_type=HierarchyNodeType.FILE,
        name="session.py",
        parent_uri="context://resources/auth/",
        abstract="Redis distributed session storage provider.",
        score=0.55,
    )

    all_nodes = [dir_node, hit_node, sibling_1, sibling_2]
    res = retriever.retrieve(query="OAuth2 authentication code", nodes=all_nodes, limit=3)

    assert len(res.hits) >= 1
    top_hit = res.hits[0]
    assert top_hit.uri == "context://resources/auth/oauth.py"
    assert top_hit.parent_uri == "context://resources/auth/"
    assert "Authentication and authorization subsystem" in (top_hit.parent_summary or "")
    # Check bundled siblings
    assert len(top_hit.sibling_contexts) == 2
    sibling_names = [sib.name for sib in top_hit.sibling_contexts]
    assert "jwt.py" in sibling_names
    assert "session.py" in sibling_names


def test_hierarchical_retrieval_convergence_and_pruning() -> None:
    """Verify convergence bounds and pruning of subtrees when directory dominates."""
    retriever = HierarchicalDirectoryDominanceRetriever(
        config=DirectoryDominanceConfig(
            dominance_ratio=1.2,
            max_convergence_rounds=3,
        )
    )

    # Macro query: directory score dominates (0.95 vs child max 0.60)
    root_dir = HierarchicalNode(
        uri="context://resources/architecture/",
        node_type=HierarchyNodeType.DIRECTORY,
        name="architecture",
        abstract="Macro enterprise system architecture overview.",
        score=0.95,
    )
    leaf_a = HierarchicalNode(
        uri="context://resources/architecture/diagram.png",
        node_type=HierarchyNodeType.FILE,
        name="diagram.png",
        parent_uri="context://resources/architecture/",
        abstract="Visual diagram asset.",
        score=0.50,
    )
    leaf_b = HierarchicalNode(
        uri="context://resources/architecture/spec.md",
        node_type=HierarchyNodeType.FILE,
        name="spec.md",
        parent_uri="context://resources/architecture/",
        abstract="Detailed micro spec.",
        score=0.60,
    )

    res_macro = retriever.retrieve(
        query="system architecture overview",
        nodes=[root_dir, leaf_a, leaf_b],
        limit=5,
    )

    assert len(res_macro.hits) == 1
    assert res_macro.hits[0].uri == "context://resources/architecture/"
    assert res_macro.hits[0].decision == DominanceDecisionKind.DIRECTORY_DOMINANT
    assert res_macro.stats.dominant_directories_count == 1
    assert res_macro.stats.convergence_rounds <= 3

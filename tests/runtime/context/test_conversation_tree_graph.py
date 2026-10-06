"""Unit tests for tree-structured conversation graph and branch replay engine."""

from myrm_agent_harness.runtime.context.conversation_tree_graph import (
    ConversationTreeGraph,
)
from myrm_agent_harness.runtime.context.conversation_tree_html_exporter import (
    ConversationTreeHtmlExporter,
)
from myrm_agent_harness.runtime.context.conversation_tree_types import (
    TreeFilterCriteria,
    TreeNodeKind,
)


def test_conversation_tree_node_addition_and_linear_projection() -> None:
    """Test sequential node addition and chronological branch projection."""
    graph = ConversationTreeGraph()

    # Turn 1
    n1 = graph.add_node(TreeNodeKind.USER, "user", "What is the capital of France?")
    n2 = graph.add_node(TreeNodeKind.ASSISTANT, "assistant", "Paris.")

    # Turn 2
    n3 = graph.add_node(TreeNodeKind.USER, "user", "What is its population?")
    n4 = graph.add_node(TreeNodeKind.ASSISTANT, "assistant", "Around 2.1 million.")

    assert graph.total_nodes() == 4
    assert graph.root_id == n1.node_id
    assert graph.current_leaf_id == n4.node_id

    # Linear projection from leaf
    path = graph.project_branch()
    assert len(path) == 4
    assert [n.node_id for n in path] == [n1.node_id, n2.node_id, n3.node_id, n4.node_id]
    assert path[0].content == "What is the capital of France?"
    assert path[-1].content == "Around 2.1 million."


def test_in_place_branch_switch_and_forking() -> None:
    """Test in-place rollback and branching from an ancestor node without losing original history."""
    graph = ConversationTreeGraph()

    # Main branch: N1 (User) -> N2 (Assistant Plan A) -> N3 (Assistant Result A)
    n1 = graph.add_node(TreeNodeKind.USER, "user", "Help me build a web server.")
    n2 = graph.add_node(TreeNodeKind.ASSISTANT, "assistant", "Let's use Flask.")
    n3 = graph.add_node(TreeNodeKind.ASSISTANT, "assistant", "Here is the Flask code.")

    # In-place switch back to N1 (rollback)
    rewound_path = graph.switch_active_node(n1.node_id)
    assert len(rewound_path) == 1
    assert graph.current_leaf_id == n1.node_id

    # Fork alternate branch from N1: N4 (Assistant Plan B) -> N5 (Assistant Result B)
    n4 = graph.add_node(TreeNodeKind.ASSISTANT, "assistant", "Let's use FastAPI instead.")
    n5 = graph.add_node(TreeNodeKind.ASSISTANT, "assistant", "Here is the FastAPI code.")

    assert graph.total_nodes() == 5

    # Check both branches exist simultaneously
    branches = graph.list_all_branches()
    assert len(branches) == 2

    # Branch A leaf: n3
    path_a = graph.project_branch(n3.node_id)
    assert [n.node_id for n in path_a] == [n1.node_id, n2.node_id, n3.node_id]
    assert "Flask" in path_a[1].content

    # Branch B leaf: n5
    path_b = graph.project_branch(n5.node_id)
    assert [n.node_id for n in path_b] == [n1.node_id, n4.node_id, n5.node_id]
    assert "FastAPI" in path_b[1].content


def test_multidimensional_filtering() -> None:
    """Test filtering projected messages by semantic kinds and timestamps."""
    graph = ConversationTreeGraph()

    n1 = graph.add_node(TreeNodeKind.USER, "user", "Query")
    graph.add_node(TreeNodeKind.REASONING, "assistant", "Deep thoughts...")
    graph.add_node(TreeNodeKind.TOOL_CALL, "assistant", "curl example.com")
    n4 = graph.add_node(TreeNodeKind.ASSISTANT, "assistant", "Final Answer")

    full_chain = graph.project_branch()
    assert len(full_chain) == 4

    # Filter only USER and ASSISTANT final messages
    criteria = TreeFilterCriteria(
        include_kinds={TreeNodeKind.USER, TreeNodeKind.ASSISTANT}
    )
    filtered = graph.filter_branch_messages(full_chain, criteria)
    assert len(filtered) == 2
    assert filtered[0].node_id == n1.node_id
    assert filtered[1].node_id == n4.node_id


def test_bookmark_management() -> None:
    """Test starring key decision nodes with bookmarks and notes."""
    graph = ConversationTreeGraph()

    graph.add_node(TreeNodeKind.USER, "user", "Choose database")
    n2 = graph.add_node(
        TreeNodeKind.ASSISTANT, "assistant", "We select PostgreSQL for ACID compliance."
    )

    # Star node N2
    ok = graph.toggle_bookmark(n2.node_id, is_bookmarked=True, note="Key Architecture Choice")
    assert ok is True

    bookmarks = graph.list_bookmarks()
    assert len(bookmarks) == 1
    assert bookmarks[0].node_id == n2.node_id
    assert bookmarks[0].note == "Key Architecture Choice"
    assert "PostgreSQL" in bookmarks[0].title

    # Node property reflected
    node = graph.get_node(n2.node_id)
    assert node is not None
    assert node.is_bookmarked is True

    # Unstar
    graph.toggle_bookmark(n2.node_id, is_bookmarked=False)
    assert len(graph.list_bookmarks()) == 0


def test_interactive_html_and_markdown_export() -> None:
    """Test generating self-contained interactive HTML and markdown tree outline."""
    graph = ConversationTreeGraph()

    graph.add_node(TreeNodeKind.USER, "user", "Root Question")
    n2 = graph.add_node(TreeNodeKind.ASSISTANT, "assistant", "Answer 1")
    graph.toggle_bookmark(n2.node_id, is_bookmarked=True, note="Initial decision")

    exporter = ConversationTreeHtmlExporter()

    # 1. HTML export
    html_doc = exporter.export_html(graph, title="Test Session Tree")
    assert "<!DOCTYPE html>" in html_doc
    assert "Test Session Tree" in html_doc
    assert "Root Question" in html_doc
    assert "Answer 1" in html_doc
    assert "const dag =" in html_doc
    assert "Initial decision" in html_doc

    # 2. Markdown outline
    md_outline = exporter.export_markdown_outline(graph)
    assert "# CONVERSATION TREE DAG OUTLINE" in md_outline
    assert "Total Nodes: 2" in md_outline
    assert "Total Branches: 1" in md_outline
    assert "Starred Bookmarks" in md_outline
    assert "Initial decision" in md_outline

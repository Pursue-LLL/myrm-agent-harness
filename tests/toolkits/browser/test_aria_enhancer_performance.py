"""Performance validation for aria_enhancer optimizations."""

from myrm_agent_harness.toolkits.browser.snapshot.aria_enhancer import enhance_aria_tree
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import AriaNode


def test_performance_large_tree(benchmark) -> None:
    """Verify performance optimization for large DOM trees using pytest-benchmark."""
    nodes = (
        [AriaNode(role="button", name=f"Button {i}", indent=0) for i in range(300)]
        + [AriaNode(role="heading", name=f"Heading {i}", indent=0) for i in range(300)]
        + [AriaNode(role="cell", name=f"Cell {i}", indent=0) for i in range(400)]
    )

    benchmark.pedantic(
        enhance_aria_tree,
        args=(nodes,),
        kwargs={"scope": "content"},
        iterations=100,
        rounds=10,
        warmup_rounds=5,
    )


def test_all_content_roles_assigned() -> None:
    """Verify all 21 CONTENT_ROLES are correctly classified."""
    content_roles = [
        "heading",
        "article",
        "section",
        "region",
        "main",
        "navigation",
        "banner",
        "contentinfo",
        "complementary",
        "cell",
        "gridcell",
        "columnheader",
        "rowheader",
        "listitem",
        "img",
        "figure",
        "term",
        "definition",
        "blockquote",
        "code",
        "note",
    ]

    nodes = [AriaNode(role=role, name=f"Test {role}", indent=0) for role in content_roles]

    _, refs = enhance_aria_tree(nodes, scope="content-only")

    assert len(refs) == 21
    assert all(ref.role in content_roles for ref in refs.values())


def test_scope_content_only_excludes_interactive() -> None:
    """Verify content-only scope correctly excludes interactive elements."""
    nodes = [
        AriaNode(role="button", name="Click", indent=0),
        AriaNode(role="link", name="Home", indent=0),
        AriaNode(role="textbox", name="Search", indent=0),
        AriaNode(role="heading", name="Title", indent=0),
        AriaNode(role="article", name="Post", indent=0),
    ]

    _, refs = enhance_aria_tree(nodes, scope="content-only")

    assert len(refs) == 2
    assert all(ref.role in ("heading", "article") for ref in refs.values())

from bs4 import BeautifulSoup

from myrm_agent_harness.toolkits.browser.snapshot.aria_types import AriaNode, EnhancedNode
from myrm_agent_harness.utils.tree_truncator import (
    _get_aria_weight,
    _get_html_weight,
    truncate_aria_tree,
    truncate_html_soup,
)


def test_html_truncation():
    # 1. Very small document, no truncation needed
    html = "<html><body><main><p>Hello World</p></main></body></html>"
    soup = BeautifulSoup(html, "lxml")
    new_soup, was_truncated = truncate_html_soup(soup, max_chars=1000)
    assert not was_truncated
    assert "Hello World" in str(new_soup)

    # 2. Document needs truncation, main tag should have higher priority
    # Let's create a doc with a huge <nav> and a small <main>
    html_nav = "<nav>" + "A" * 1000 + "</nav>"
    html_main = "<main>" + "B" * 100 + "</main>"
    html = f"<html><body>{html_nav}{html_main}</body></html>"
    soup = BeautifulSoup(html, "lxml")

    # Nav is 1000 chars * 0.2 = 200 mass
    # Main is 100 chars * 2.0 = 200 mass
    # So they should get roughly equal budget, but nav needs 1000, main needs 100.
    # If we limit to 300 chars, nav will be truncated, main will be kept.
    new_soup, was_truncated = truncate_html_soup(soup, max_chars=300)
    assert was_truncated

    result_str = str(new_soup)
    assert "BBBB" in result_str, "Main content should be preserved due to high weight"
    assert "AAAA" in result_str
    assert "[TRUNCATED]" in result_str

def test_aria_truncation():
    # Construct a tree
    # root
    #  |- main (role=main)
    #  |   |- button (role=button)
    #  |- nav (role=navigation)
    #      |- link (role=link)

    main_node = EnhancedNode(node=AriaNode(role="main", name="Main Content"), children=(
        EnhancedNode(node=AriaNode(role="button", name="Click Me " * 10)),
    ))

    nav_node = EnhancedNode(node=AriaNode(role="navigation", name="Nav Menu"), children=(
        EnhancedNode(node=AriaNode(role="link", name="Link " * 100)),
    ))

    root = EnhancedNode(node=AriaNode(role="document", name="Doc"), children=(main_node, nav_node))

    # 1. No truncation
    nodes, was_truncated = truncate_aria_tree([root], max_tokens=10000)
    assert not was_truncated
    assert len(nodes) == 1

    # 2. Truncation
    # Link is huge, Nav weight is 0.2. Main weight is 2.0.
    nodes, was_truncated = truncate_aria_tree([root], max_tokens=20) # 80 chars
    assert was_truncated
    assert len(nodes) == 1

    # Check that it reached TRUNCATED
    def has_truncated(n: EnhancedNode) -> bool:
        if "[TRUNCATED]" in n.node.name:
            return True
        return any(has_truncated(c) for c in n.children)

    assert has_truncated(nodes[0])

def test_weights():
    # HTML
    class MockTag:
        def __init__(self, name):
            self.name = name

    assert _get_html_weight(MockTag("article")) == 2.0
    assert _get_html_weight(MockTag("nav")) == 0.2
    assert _get_html_weight(MockTag("div")) == 1.0

    # ARIA
    assert _get_aria_weight("main") == 2.0
    assert _get_aria_weight("navigation") == 0.2
    assert _get_aria_weight("group") == 1.0

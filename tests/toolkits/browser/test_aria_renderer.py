"""Tests for aria_renderer (Layer 4) - text formatting."""

from myrm_agent_harness.toolkits.browser.snapshot.aria_renderer import render_to_yaml
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import AriaNode, EnhancedNode


class TestAriaRenderer:
    """Test suite for ARIA tree renderer."""

    def test_render_yaml_format(self) -> None:
        """Test rendering to YAML format."""
        node = AriaNode(role="button", name="Submit", indent=0)
        enhanced = EnhancedNode(node=node, ref_id="e0", position="at top-left")

        text, meta = render_to_yaml([enhanced], compact=False)

        assert '- button "Submit" [ref=e0] at top-left' in text
        assert meta.ref_count == 1
        assert meta.estimated_tokens > 0

    def test_render_compact_format(self) -> None:
        """Test rendering to compact format."""
        node = AriaNode(role="button", name="Submit", indent=0)
        enhanced = EnhancedNode(node=node, ref_id="e0", position="at center")

        text, meta = render_to_yaml([enhanced], compact=True)

        assert text == "e0:button at center"
        assert meta.ref_count == 1

    def test_render_without_position(self) -> None:
        """Test rendering without semantic position."""
        node = AriaNode(role="link", name="Home", indent=0)
        enhanced = EnhancedNode(node=node, ref_id="e0")

        text, _ = render_to_yaml([enhanced], compact=False)

        assert '- link "Home" [ref=e0]' in text
        assert " at " not in text

    def test_render_nested_tree(self) -> None:
        """Test rendering nested tree structure."""
        child_node = AriaNode(role="button", name="Click", indent=1)
        child_enhanced = EnhancedNode(node=child_node, ref_id="e1")

        parent_node = AriaNode(role="navigation", name="Nav", children=[child_node], indent=0)
        parent_enhanced = EnhancedNode(node=parent_node, ref_id="e0", children=[child_enhanced])

        text, meta = render_to_yaml([parent_enhanced], compact=False)

        assert '- navigation "Nav" [ref=e0]' in text
        assert '  - button "Click" [ref=e1]' in text
        assert meta.ref_count == 2

    def test_render_without_ref(self) -> None:
        """Test rendering elements without ref IDs."""
        node = AriaNode(role="generic", name="", indent=0)
        enhanced = EnhancedNode(node=node)

        text, meta = render_to_yaml([enhanced], compact=False)

        assert '- generic ""' in text
        assert "[ref=" not in text
        assert meta.ref_count == 0

    def test_render_compact_skips_non_ref(self) -> None:
        """Test compact mode skips elements without refs."""
        node1 = AriaNode(role="button", name="Submit", indent=0)
        enhanced1 = EnhancedNode(node=node1, ref_id="e0")

        node2 = AriaNode(role="generic", name="", indent=0)
        enhanced2 = EnhancedNode(node=node2)

        text, meta = render_to_yaml([enhanced1, enhanced2], compact=True)

        assert "e0:button" in text
        assert "generic" not in text
        assert meta.ref_count == 1

    def test_render_with_attributes(self) -> None:
        """Test rendering with ARIA attributes."""
        node = AriaNode(role="button", name="Toggle", attributes={"pressed": "true"}, indent=0)
        enhanced = EnhancedNode(node=node, ref_id="e0")

        text, _ = render_to_yaml([enhanced], compact=False)

        assert "[pressed=true]" in text

    def test_render_empty_tree(self) -> None:
        """Test rendering empty tree."""
        text, meta = render_to_yaml([], compact=False)

        assert text == ""
        assert meta.ref_count == 0
        assert meta.estimated_tokens == 0

    def test_token_estimation(self) -> None:
        """Test token estimation accuracy."""
        node = AriaNode(role="button", name="A" * 100, indent=0)  # 100 chars
        enhanced = EnhancedNode(node=node, ref_id="e0")

        _, meta = render_to_yaml([enhanced], compact=False)

        # Estimated tokens should be roughly chars / 4
        assert meta.estimated_tokens > 20
        assert meta.estimated_tokens < 50

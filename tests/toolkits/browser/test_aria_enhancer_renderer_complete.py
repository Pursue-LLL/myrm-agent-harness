"""Complete coverage tests for ARIA enhancer and renderer (Layer 3 & 4).

Tests for aria_enhancer.py and aria_renderer.py modules.
"""

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.aria_enhancer import (
    _role_in_scope,
    enhance_aria_tree,
)
from myrm_agent_harness.toolkits.browser.snapshot.aria_renderer import render_to_yaml
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import (
    AriaNode,
    BBox,
    EnhancedNode,
    calculate_semantic_position,
)


class TestAriaEnhancerCoverage:
    """Complete coverage for aria_enhancer."""

    def test_role_in_scope_all_scopes(self) -> None:
        """Test _role_in_scope for all scope values."""
        assert _role_in_scope("button", "interactive") is True
        assert _role_in_scope("heading", "interactive") is False
        assert _role_in_scope("generic", "interactive") is False

        assert _role_in_scope("button", "content") is True
        assert _role_in_scope("heading", "content") is True
        assert _role_in_scope("generic", "content") is False

        assert _role_in_scope("button", "full") is True
        assert _role_in_scope("heading", "full") is True
        assert _role_in_scope("generic", "full") is True

        assert _role_in_scope("button", "unknown") is True
        assert _role_in_scope("heading", "unknown") is False

    def test_calculate_semantic_position_all_grid_cells(self) -> None:
        """Test calculate_semantic_position for all 9 grid positions."""
        vw, vh = 1920, 1080

        bbox = BBox(0, 0, 100, 50, int(vw * 0.15), int(vh * 0.15), vw, vh)
        assert calculate_semantic_position(bbox) == "at top-left"

        bbox = BBox(0, 0, 100, 50, int(vw * 0.5), int(vh * 0.15), vw, vh)
        assert calculate_semantic_position(bbox) == "at top"

        bbox = BBox(0, 0, 100, 50, int(vw * 0.85), int(vh * 0.15), vw, vh)
        assert calculate_semantic_position(bbox) == "at top-right"

        bbox = BBox(0, 0, 100, 50, int(vw * 0.15), int(vh * 0.5), vw, vh)
        assert calculate_semantic_position(bbox) == "at left"

        bbox = BBox(0, 0, 100, 50, int(vw * 0.5), int(vh * 0.5), vw, vh)
        assert calculate_semantic_position(bbox) == "at center"

        bbox = BBox(0, 0, 100, 50, int(vw * 0.85), int(vh * 0.5), vw, vh)
        assert calculate_semantic_position(bbox) == "at right"

        bbox = BBox(0, 0, 100, 50, int(vw * 0.15), int(vh * 0.85), vw, vh)
        assert calculate_semantic_position(bbox) == "at bottom-left"

        bbox = BBox(0, 0, 100, 50, int(vw * 0.5), int(vh * 0.85), vw, vh)
        assert calculate_semantic_position(bbox) == "at bottom"

        bbox = BBox(0, 0, 100, 50, int(vw * 0.85), int(vh * 0.85), vw, vh)
        assert calculate_semantic_position(bbox) == "at bottom-right"

    def test_immutable_enhanced_node(self) -> None:
        """Test EnhancedNode immutability (frozen dataclass)."""
        node1 = AriaNode(role="nav", name="Nav")
        node2 = AriaNode(role="button", name="B1")
        node3 = AriaNode(role="button", name="B2")

        enhanced1 = EnhancedNode(
            node=node1,
            ref_id="e0",
            children=(
                EnhancedNode(node=node2, ref_id="e1"),
                EnhancedNode(node=node3, ref_id="e2"),
            ),
        )

        assert len(enhanced1.children) == 2
        assert enhanced1.children[0].ref_id == "e1"
        assert enhanced1.children[1].ref_id == "e2"

        # Verify immutability
        with pytest.raises(AttributeError):
            enhanced1.nth = 5  # type: ignore[misc]

    def test_enhance_with_viewport_defaults(self) -> None:
        """Test enhancement when viewport info is missing in bbox_map."""
        nodes = [AriaNode(role="button", name="Test")]
        bbox_map = {
            "button:Test": {
                "x": 10,
                "y": 20,
                "width": 100,
                "height": 50,
                "centerX": 60,
                "centerY": 45,
                "viewport": {"width": 1920, "height": 1080},
            }
        }

        _enhanced, refs = enhance_aria_tree(nodes, scope="interactive", bbox_map=bbox_map)

        assert refs["e0"].bbox is not None
        assert refs["e0"].bbox.viewport_width == 1920
        assert refs["e0"].bbox.viewport_height == 1080

    def test_enhance_multiple_duplicates(self) -> None:
        """Test enhancement with multiple duplicates (3+ same elements)."""
        nodes = [
            AriaNode(role="button", name="Next"),
            AriaNode(role="button", name="Next"),
            AriaNode(role="button", name="Next"),
        ]

        _enhanced, refs = enhance_aria_tree(nodes, scope="interactive")

        assert refs["e0"].nth == 0
        assert refs["e1"].nth == 1
        assert refs["e2"].nth == 2

    def test_enhance_mixed_roles(self) -> None:
        """Test enhancement with all three role types."""
        nodes = [
            AriaNode(role="button", name="Interactive"),
            AriaNode(role="heading", name="Content"),
            AriaNode(role="generic", name="Structural"),
        ]

        _enhanced_int, refs_int = enhance_aria_tree(nodes, scope="interactive")
        assert len(refs_int) == 1

        _enhanced_con, refs_con = enhance_aria_tree(nodes, scope="content")
        assert len(refs_con) == 2

        _enhanced_full, refs_full = enhance_aria_tree(nodes, scope="full")
        assert len(refs_full) == 3


class TestAriaRendererCoverage:
    """Complete coverage for aria_renderer."""

    def test_render_with_multiple_attributes(self) -> None:
        """Test rendering with multiple ARIA attributes."""
        node = AriaNode(
            role="button",
            name="Toggle",
            attributes={"pressed": "true", "disabled": "false", "aria-expanded": "true"},
        )
        enhanced = EnhancedNode(node=node, ref_id="e0")

        text, _ = render_to_yaml([enhanced], compact=False)

        assert "[pressed=true]" in text
        assert "[disabled=false]" in text
        assert "[aria-expanded=true]" in text

    def test_render_empty_name(self) -> None:
        """Test rendering element with empty name."""
        node = AriaNode(role="generic", name="")
        enhanced = EnhancedNode(node=node)

        text, _ = render_to_yaml([enhanced], compact=False)

        assert '- generic ""' in text

    def test_render_deeply_nested(self) -> None:
        """Test rendering deeply nested tree (3+ levels)."""
        child3 = AriaNode(role="button", name="Deep", indent=3)
        enhanced3 = EnhancedNode(node=child3, ref_id="e2")

        child2 = AriaNode(role="list", name="", children=[child3], indent=2)
        enhanced2 = EnhancedNode(node=child2, children=[enhanced3])

        child1 = AriaNode(role="nav", name="Nav", children=[child2], indent=1)
        enhanced1 = EnhancedNode(node=child1, ref_id="e0", children=[enhanced2])

        root = AriaNode(role="WebArea", name="", children=[child1], indent=0)
        enhanced_root = EnhancedNode(node=root, ref_id="e1", children=[enhanced1])

        text, meta = render_to_yaml([enhanced_root], compact=False)

        lines = text.split("\n")
        assert len([line for line in lines if "- WebArea" in line]) == 1
        assert len([line for line in lines if "  - nav" in line]) == 1
        assert len([line for line in lines if "    - list" in line]) == 1
        assert len([line for line in lines if "      - button" in line]) == 1
        assert meta.ref_count == 3

    def test_render_compact_mixed_ref_and_non_ref(self) -> None:
        """Test compact mode with mixed ref and non-ref elements."""
        nodes = [
            AriaNode(role="button", name="A"),
            AriaNode(role="generic", name=""),
            AriaNode(role="link", name="B"),
        ]

        enhanced1 = EnhancedNode(node=nodes[0], ref_id="e0")
        enhanced2 = EnhancedNode(node=nodes[1])
        enhanced3 = EnhancedNode(node=nodes[2], ref_id="e1")

        text, meta = render_to_yaml([enhanced1, enhanced2, enhanced3], compact=True)

        assert "e0:button" in text
        assert "e1:link" in text
        assert "generic" not in text
        assert meta.ref_count == 2

    def test_render_token_estimation_edge_cases(self) -> None:
        """Test token estimation with various text lengths."""
        _, meta = render_to_yaml([], compact=False)
        assert meta.estimated_tokens == 0

        node = AriaNode(role="b", name="X")
        enhanced = EnhancedNode(node=node, ref_id="e0")
        _, meta = render_to_yaml([enhanced], compact=False)
        assert meta.estimated_tokens >= 1

        node = AriaNode(role="button", name="A" * 1000)
        enhanced = EnhancedNode(node=node, ref_id="e0")
        _, meta = render_to_yaml([enhanced], compact=False)
        assert meta.estimated_tokens > 200

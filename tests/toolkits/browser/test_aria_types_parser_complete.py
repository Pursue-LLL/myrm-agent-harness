"""Complete coverage tests for ARIA types and parser (Layer 2).

Tests for aria_types.py and aria_parser.py modules.
"""

from myrm_agent_harness.toolkits.browser.snapshot.aria_parser import (
    _parse_yaml_nodes,
    parse_aria_yaml,
)
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import AriaNode, BBox, EnhancedNode


class TestAriaTypesCoverage:
    """Test AriaNode and EnhancedNode data structures."""

    def test_aria_node_initialization_full(self) -> None:
        """Test AriaNode with all parameters."""
        node = AriaNode(
            role="button",
            name="Submit",
            attributes={"pressed": "true"},
            children=[AriaNode(role="text", name="Click")],
            indent=2,
        )
        assert node.role == "button"
        assert node.name == "Submit"
        assert node.attributes == {"pressed": "true"}
        assert len(node.children) == 1
        assert node.indent == 2
        assert "button" in repr(node)

    def test_aria_node_defaults(self) -> None:
        """Test AriaNode with default parameters."""
        node = AriaNode(role="link")
        assert node.name == ""
        assert node.attributes == {}
        assert node.children == []
        assert node.indent == 0

    def test_enhanced_node_initialization_full(self) -> None:
        """Test EnhancedNode with all parameters."""
        aria_node = AriaNode(role="button", name="Test")
        bbox = BBox(10, 20, 100, 50, 60, 45, 10, 20, 1920, 1080)
        enhanced = EnhancedNode(
            node=aria_node,
            ref_id="e0",
            bbox=bbox,
            position="at top-left",
            nth=0,
            children=(),
        )
        assert enhanced.node == aria_node
        assert enhanced.ref_id == "e0"
        assert enhanced.bbox == bbox
        assert enhanced.position == "at top-left"
        assert enhanced.nth == 0
        assert "e0" in repr(enhanced)

    def test_enhanced_node_defaults(self) -> None:
        """Test EnhancedNode with minimal parameters."""
        aria_node = AriaNode(role="generic")
        enhanced = EnhancedNode(node=aria_node)
        assert enhanced.ref_id is None
        assert enhanced.bbox is None
        assert enhanced.position is None
        assert enhanced.nth is None
        assert enhanced.children == ()

    def test_bbox_namedtuple(self) -> None:
        """Test BBox NamedTuple properties."""
        bbox = BBox(10, 20, 100, 50, 60, 45, 10, 20, 1920, 1080)
        assert bbox.x == 10
        assert bbox.y == 20
        assert bbox.width == 100
        assert bbox.height == 50
        assert bbox.centerX == 60
        assert bbox.centerY == 45
        assert bbox.viewport_width == 1920
        assert bbox.viewport_height == 1080


class TestAriaParserCoverage:
    """Complete coverage for aria_parser."""

    def test_parse_yaml_nodes_list_variant(self) -> None:
        """Test _parse_yaml_nodes with list input."""
        data = [{"button": {"name": "A"}}, {"link": {"name": "B"}}]
        nodes = _parse_yaml_nodes(data, indent=0)
        assert len(nodes) == 2
        assert nodes[0].role == "button"
        assert nodes[1].role == "link"

    def test_parse_yaml_nodes_dict_variant(self) -> None:
        """Test _parse_yaml_nodes with dict input."""
        data = {"button": {"name": "Submit", "pressed": "true"}}
        nodes = _parse_yaml_nodes(data, indent=1)
        assert len(nodes) == 1
        assert nodes[0].role == "button"
        assert nodes[0].name == "Submit"
        assert nodes[0].attributes["pressed"] == "true"
        assert nodes[0].indent == 1

    def test_parse_yaml_nodes_string_value(self) -> None:
        """Test _parse_yaml_nodes with string value."""
        data = {"button": "Button Text"}
        nodes = _parse_yaml_nodes(data, indent=0)
        assert len(nodes) == 1
        assert nodes[0].name == "Button Text"
        assert nodes[0].attributes == {}

    def test_parse_yaml_nodes_none_value(self) -> None:
        """Test _parse_yaml_nodes with None value."""
        data = {"button": None}
        nodes = _parse_yaml_nodes(data, indent=0)
        assert len(nodes) == 1
        assert nodes[0].name == ""

    def test_parse_yaml_nodes_empty_input(self) -> None:
        """Test _parse_yaml_nodes with empty/None input."""
        assert _parse_yaml_nodes(None) == []
        assert _parse_yaml_nodes([]) == []
        assert _parse_yaml_nodes({}) == []

    def test_parse_yaml_nodes_unexpected_type(self) -> None:
        """Test _parse_yaml_nodes with bare identifier string falls back to role token."""
        result = _parse_yaml_nodes("unexpected string", indent=0)
        assert len(result) == 1
        assert result[0].role == "unexpected"
        assert result[0].name == ""

        result_non_ident = _parse_yaml_nodes("123 not-valid", indent=0)
        assert result_non_ident == []

    def test_parse_yaml_nodes_unexpected_non_string_type(self) -> None:
        """Test _parse_yaml_nodes with unexpected non-string types."""
        result = _parse_yaml_nodes(123, indent=0)
        assert result == []

        result = _parse_yaml_nodes(3.14, indent=0)
        assert result == []

        result = _parse_yaml_nodes(True, indent=0)
        assert result == []

    def test_parse_yaml_nodes_dict_unexpected_value_type(self) -> None:
        """Test _parse_yaml_nodes with unexpected value type in dict."""
        data = {"button": 123}
        nodes = _parse_yaml_nodes(data, indent=0)
        assert len(nodes) == 0

    def test_parse_yaml_nodes_nested_children(self) -> None:
        """Test _parse_yaml_nodes with nested children."""
        data = {
            "WebArea": {
                "name": "Page",
                "children": [{"button": {"name": "A"}}, {"link": {"name": "B"}}],
            }
        }
        nodes = _parse_yaml_nodes(data, indent=0)
        assert len(nodes) == 1
        assert len(nodes[0].children) == 2

    def test_parse_aria_yaml_whitespace_only(self) -> None:
        """Test parse_aria_yaml with whitespace-only input."""
        assert parse_aria_yaml("   \n  \n  ") == []

    def test_parse_aria_yaml_none_result(self) -> None:
        """Test parse_aria_yaml with YAML that loads to None."""
        yaml_str = "~"
        result = parse_aria_yaml(yaml_str)
        assert result == []

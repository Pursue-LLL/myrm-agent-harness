"""Integration tests for four-layer ARIA snapshot pipeline."""

from myrm_agent_harness.toolkits.browser.snapshot.aria_enhancer import enhance_aria_tree
from myrm_agent_harness.toolkits.browser.snapshot.aria_parser import parse_aria_yaml
from myrm_agent_harness.toolkits.browser.snapshot.aria_renderer import render_to_yaml


class TestAriaPipeline:
    """Test suite for end-to-end ARIA snapshot pipeline."""

    def test_full_pipeline_yaml_to_enhanced_text(self) -> None:
        """Test complete pipeline: YAML -> parse -> enhance -> render."""
        yaml_input = """
- WebArea:
    name: "Test Page"
    children:
      - button:
          name: "Submit"
      - link:
          name: "Home"
"""

        # Layer 2: Parse
        nodes = parse_aria_yaml(yaml_input)
        assert len(nodes) == 1
        assert nodes[0].role == "WebArea"

        # Layer 3: Enhance
        enhanced, refs = enhance_aria_tree(nodes, scope="interactive")
        assert len(refs) == 2
        assert "e0" in refs
        assert "e1" in refs

        # Layer 4: Render
        text, meta = render_to_yaml(enhanced, compact=False)
        assert "[ref=e0]" in text
        assert "[ref=e1]" in text
        assert meta.ref_count == 2

    def test_pipeline_with_bbox_and_position(self) -> None:
        """Test pipeline with bbox data and semantic position."""
        yaml_input = """
- button:
    name: "Top Button"
"""

        bbox_map = {
            "button:Top Button": {
                "x": 100,
                "y": 50,
                "width": 200,
                "height": 40,
                "centerX": 200,
                "centerY": 70,
                "viewport": {"width": 1920, "height": 1080},
            }
        }

        nodes = parse_aria_yaml(yaml_input)
        enhanced, refs = enhance_aria_tree(nodes, scope="interactive", bbox_map=bbox_map)
        text, _ = render_to_yaml(enhanced, compact=False)

        assert "at top-left" in text
        assert refs["e0"].position == "at top-left"
        assert refs["e0"].bbox is not None

    def test_pipeline_compact_mode(self) -> None:
        """Test pipeline with compact rendering."""
        yaml_input = """
- button:
    name: "Submit"
- generic:
    name: ""
"""

        nodes = parse_aria_yaml(yaml_input)
        enhanced, _refs = enhance_aria_tree(nodes, scope="interactive", compact=True)
        text, meta = render_to_yaml(enhanced, compact=True)

        assert "e0:button" in text
        assert "generic" not in text  # structural element skipped in compact
        assert meta.ref_count == 1

    def test_pipeline_nth_deduplication(self) -> None:
        """Test pipeline handles duplicate elements correctly."""
        yaml_input = """
- button:
    name: "Next"
- button:
    name: "Next"
- button:
    name: "Prev"
"""

        nodes = parse_aria_yaml(yaml_input)
        _enhanced, refs = enhance_aria_tree(nodes, scope="interactive")

        # Two "Next" buttons should have nth, "Prev" should not
        assert refs["e0"].nth == 0
        assert refs["e1"].nth == 1
        assert refs["e2"].nth is None

    def test_pipeline_scope_filtering(self) -> None:
        """Test pipeline respects scope parameter."""
        yaml_input = """
- button:
    name: "Click"
- heading:
    name: "Title"
- generic:
    name: "wrapper"
"""

        nodes = parse_aria_yaml(yaml_input)

        # Interactive scope: only button
        _enhanced_int, refs_int = enhance_aria_tree(nodes, scope="interactive")
        assert len(refs_int) == 1
        assert refs_int["e0"].role == "button"

        # Content scope: button + heading
        _enhanced_con, refs_con = enhance_aria_tree(nodes, scope="content")
        assert len(refs_con) == 2

        # Full scope: all elements
        _enhanced_full, refs_full = enhance_aria_tree(nodes, scope="full")
        assert len(refs_full) == 3

    def test_pipeline_preserves_hierarchy(self) -> None:
        """Test pipeline preserves tree hierarchy through all layers."""
        yaml_input = """
- WebArea:
    children:
      - navigation:
          children:
            - button:
                name: "Menu"
"""

        nodes = parse_aria_yaml(yaml_input)
        enhanced, _refs = enhance_aria_tree(nodes, scope="content")
        text, _ = render_to_yaml(enhanced, compact=False)

        # Check indentation preserved
        lines = text.split("\n")
        assert any(line.startswith("- WebArea") for line in lines)
        assert any(line.startswith("  - navigation") for line in lines)
        assert any(line.startswith("    - button") for line in lines)

    def test_pipeline_unicode_safety(self) -> None:
        """Test pipeline handles Unicode correctly."""
        yaml_input = """
- button:
    name: "提交 "
"""

        nodes = parse_aria_yaml(yaml_input)
        enhanced, refs = enhance_aria_tree(nodes, scope="interactive")
        text, _ = render_to_yaml(enhanced, compact=False)

        assert "提交 " in text
        assert refs["e0"].name == "提交 "

    def test_pipeline_empty_input(self) -> None:
        """Test pipeline handles empty input gracefully."""
        nodes = parse_aria_yaml("")
        enhanced, refs = enhance_aria_tree(nodes, scope="interactive")
        text, meta = render_to_yaml(enhanced, compact=False)

        assert text == ""
        assert len(refs) == 0
        assert meta.ref_count == 0

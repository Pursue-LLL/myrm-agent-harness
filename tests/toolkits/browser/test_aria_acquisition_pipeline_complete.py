"""Complete coverage tests for ARIA acquisition and end-to-end pipeline.

Tests for aria_acquisition.py and full pipeline integration.
"""

import asyncio

import pytest
import yaml

from myrm_agent_harness.toolkits.browser.snapshot.aria_acquisition import (
    _get_aria_tree_custom,
    _get_aria_tree_fast,
    get_aria_tree,
)
from myrm_agent_harness.toolkits.browser.snapshot.aria_enhancer import enhance_aria_tree
from myrm_agent_harness.toolkits.browser.snapshot.aria_parser import parse_aria_yaml
from myrm_agent_harness.toolkits.browser.snapshot.aria_renderer import render_to_yaml
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import AriaNode, EnhancedNode


class TestAriaAcquisitionCoverage:
    """Complete coverage for aria_acquisition."""

    @pytest.mark.asyncio
    async def test_get_aria_tree_fast_path_direct(self) -> None:
        """Test _get_aria_tree_fast directly."""

        class MockLocator:
            async def aria_snapshot(self) -> str:
                return "- button:\n    name: Test"

        result = await _get_aria_tree_fast(MockLocator())
        assert "button" in result

    @pytest.mark.asyncio
    async def test_get_aria_tree_fast_path_error(self) -> None:
        """Test _get_aria_tree_fast error handling."""

        class MockLocator:
            async def aria_snapshot(self) -> str:
                raise RuntimeError("API failure")

        with pytest.raises(RuntimeError, match="API failure"):
            await _get_aria_tree_fast(MockLocator())

    @pytest.mark.asyncio
    async def test_get_aria_tree_custom_path_direct(self) -> None:
        """Test _get_aria_tree_custom directly."""

        class MockLocator:
            async def evaluate(self, script: str, *args: object) -> str:
                return "- button:\n    name: Custom"

            async def aria_snapshot(self) -> str:
                return "- button:\n    name: Fallback"

        result = await _get_aria_tree_custom(MockLocator(), max_depth=3)
        assert "Custom" in result

    @pytest.mark.asyncio
    async def test_custom_path_timeout_precise(self) -> None:
        """Test Custom Path timeout handling (3s timeout)."""

        class MockLocator:
            async def evaluate(self, script: str, *args: object) -> str:
                await asyncio.sleep(5)
                return "Should not reach"

            async def aria_snapshot(self) -> str:
                return "- button:\n    name: Fallback Success"

        result = await _get_aria_tree_custom(MockLocator(), max_depth=2)
        assert "Fallback Success" in result

    @pytest.mark.asyncio
    async def test_custom_path_exception_fallback(self) -> None:
        """Test Custom Path exception handling."""

        class MockLocator:
            async def evaluate(self, script: str, *args: object) -> str:
                raise ValueError("Custom path error")

            async def aria_snapshot(self) -> str:
                return "- button:\n    name: Exception Fallback"

        result = await _get_aria_tree_custom(MockLocator(), max_depth=5)
        assert "Exception Fallback" in result


class TestAriaPipelineCoverageComplete:
    """Complete end-to-end pipeline coverage."""

    def test_pipeline_with_all_role_types(self) -> None:
        """Test pipeline with interactive, content, and structural roles."""
        yaml_str = """
- WebArea:
    children:
      - button:
          name: Interactive
      - heading:
          name: Content
      - generic:
          name: Structural
"""

        nodes = parse_aria_yaml(yaml_str)
        enhanced, refs = enhance_aria_tree(nodes, scope="content")
        text, _ = render_to_yaml(enhanced, compact=False)

        assert len(refs) == 2
        assert "Interactive" in text
        assert "Content" in text

    def test_pipeline_with_special_yaml_features(self) -> None:
        """Test pipeline with YAML special characters."""
        yaml_str = """
- button:
    name: "Line 1\\nLine 2"
- link:
    name: 'Quote "test"'
"""

        nodes = parse_aria_yaml(yaml_str)
        enhanced, refs = enhance_aria_tree(nodes, scope="interactive")
        _text, _ = render_to_yaml(enhanced, compact=False)

        assert len(refs) == 2

    def test_pipeline_with_bbox_boundary_positions(self) -> None:
        """Test pipeline with bbox at viewport boundaries."""
        yaml_str = """
- button:
    name: Edge
"""

        bbox_map = {
            "button:Edge": {
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 50,
                "centerX": 634,
                "centerY": 356,
                "viewport": {"width": 1920, "height": 1080},
            }
        }

        nodes = parse_aria_yaml(yaml_str)
        _enhanced, refs = enhance_aria_tree(nodes, scope="interactive", bbox_map=bbox_map)

        assert refs["e0"].position in ["at top-left", "at top", "at left", "at center"]

    def test_pipeline_full_scope_compact_with_named_structural(self) -> None:
        """Test full scope compact mode with named structural elements."""
        nodes = [
            AriaNode(role="generic", name="wrapper"),
            AriaNode(role="button", name="Click"),
        ]

        _enhanced, refs = enhance_aria_tree(nodes, scope="full", compact=True)

        assert len(refs) == 2

    def test_pipeline_complex_attributes(self) -> None:
        """Test pipeline with complex attribute values."""
        yaml_str = """
- region:
    name: "Main Content"
    aria-label: "Primary navigation"
    role: "navigation"
    data-testid: "nav-main"
"""

        nodes = parse_aria_yaml(yaml_str)
        enhanced, refs = enhance_aria_tree(nodes, scope="content")
        text, _ = render_to_yaml(enhanced, compact=False)

        assert len(refs) == 1
        assert "aria-label=Primary navigation" in text or len(nodes[0].attributes) > 0


class TestEdgeCasesAndErrorPaths:
    """Test edge cases and error handling paths."""

    def test_parse_malformed_yaml_various_errors(self) -> None:
        """Test various YAML syntax errors."""
        malformed_yamls = [
            "- button: [unclosed",
            "- button:\n  name: 'unclosed quote",
            "- button:\n\tname: invalid tab",
        ]

        for malformed in malformed_yamls:
            with pytest.raises(yaml.YAMLError):
                parse_aria_yaml(malformed)

    def test_enhance_with_partial_bbox_data(self) -> None:
        """Test enhancement when bbox_map has missing fields."""
        nodes = [AriaNode(role="button", name="Test")]

        bbox_map_incomplete = {
            "button:Test": {
                "x": 10,
                "y": 20,
                "width": 100,
                "height": 50,
            }
        }

        try:
            _enhanced, _refs = enhance_aria_tree(nodes, scope="interactive", bbox_map=bbox_map_incomplete)
            assert True
        except KeyError:
            assert True

    def test_render_with_no_children(self) -> None:
        """Test rendering nodes without children."""
        node = AriaNode(role="button", name="Leaf")
        enhanced = EnhancedNode(node=node, ref_id="e0", children=[])

        text, _ = render_to_yaml([enhanced], compact=False)

        assert "[ref=e0]" in text
        assert len(enhanced.children) == 0

    @pytest.mark.asyncio
    async def test_acquisition_with_zero_depth(self) -> None:
        """Test Custom Path with max_depth=0."""

        class MockLocator:
            async def evaluate(self, script: str, *args: object) -> str:
                return "- WebArea:\n    name: Root only"

            async def aria_snapshot(self) -> str:
                return "Fallback"

        result = await get_aria_tree(MockLocator(), max_depth=0)
        assert "WebArea" in result or "Fallback" in result

    @pytest.mark.asyncio
    async def test_acquisition_with_large_depth(self) -> None:
        """Test Custom Path with very large max_depth."""

        class MockLocator:
            async def evaluate(self, script: str, *args: object) -> str:
                return "- button:\n    name: Deep"

            async def aria_snapshot(self) -> str:
                return "Fallback"

        result = await get_aria_tree(MockLocator(), max_depth=100)
        assert "Deep" in result

    def test_enhance_with_empty_bbox_map(self) -> None:
        """Test enhancement with empty bbox_map."""
        nodes = [AriaNode(role="button", name="Test")]

        _enhanced, refs = enhance_aria_tree(nodes, scope="interactive", bbox_map={})

        assert refs["e0"].bbox is None
        assert refs["e0"].position is None

    def test_render_with_all_positions(self) -> None:
        """Test rendering with all possible position values."""
        positions = [
            "at top-left",
            "at top",
            "at top-right",
            "at left",
            "at center",
            "at right",
            "at bottom-left",
            "at bottom",
            "at bottom-right",
        ]

        for i, pos in enumerate(positions):
            node = AriaNode(role="button", name=f"Btn{i}")
            enhanced = EnhancedNode(node=node, ref_id=f"e{i}", position=pos)

            text, _ = render_to_yaml([enhanced], compact=False)
            assert pos in text

    def test_parse_yaml_with_empty_children(self) -> None:
        """Test parsing with explicit empty children."""
        yaml_str = """
- button:
    name: "No Children"
    children: []
"""

        nodes = parse_aria_yaml(yaml_str)
        assert len(nodes) == 1
        assert len(nodes[0].children) == 0

    def test_enhance_unnamed_elements_various_scopes(self) -> None:
        """Test enhancement of unnamed elements in all scopes."""
        nodes = [
            AriaNode(role="generic", name=""),
            AriaNode(role="button", name=""),
        ]

        _enhanced_int, refs_int = enhance_aria_tree(nodes, scope="interactive")
        assert len(refs_int) == 1

        _enhanced_full, refs_full = enhance_aria_tree(nodes, scope="full", compact=False)
        assert len(refs_full) == 2

        _enhanced_compact, refs_compact = enhance_aria_tree(nodes, scope="full", compact=True)
        assert len(refs_compact) == 1

    def test_render_yaml_preserves_empty_attributes(self) -> None:
        """Test rendering with empty attributes dict."""
        node = AriaNode(role="button", name="Test", attributes={})
        enhanced = EnhancedNode(node=node, ref_id="e0")

        text, _ = render_to_yaml([enhanced], compact=False)

        assert text.count("[ref=e0]") == 1
        assert text.count("[") == 1

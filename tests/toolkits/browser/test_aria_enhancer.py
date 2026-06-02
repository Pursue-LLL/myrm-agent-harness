"""Tests for aria_enhancer (Layer 3) - ref ID assignment and enhancement."""

from myrm_agent_harness.toolkits.browser.snapshot.aria_enhancer import enhance_aria_tree
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import AriaNode


class TestAriaEnhancer:
    """Test suite for ARIA tree enhancer."""

    def test_enhance_interactive_scope(self) -> None:
        """Test enhancement with interactive scope."""
        nodes = [
            AriaNode(role="button", name="Submit", indent=0),
            AriaNode(role="link", name="Home", indent=0),
            AriaNode(role="generic", name="", indent=0),  # structural, no ref
        ]

        enhanced, refs = enhance_aria_tree(nodes, scope="interactive")

        assert len(refs) == 2
        assert enhanced[0].ref_id == "e0"
        assert enhanced[1].ref_id == "e1"
        assert enhanced[2].ref_id is None  # structural element

    def test_enhance_content_scope(self) -> None:
        """Test enhancement with content scope."""
        nodes = [
            AriaNode(role="button", name="Submit", indent=0),  # interactive
            AriaNode(role="heading", name="Title", indent=0),  # content
            AriaNode(role="generic", name="", indent=0),  # structural, no ref
        ]

        enhanced, refs = enhance_aria_tree(nodes, scope="content")

        assert len(refs) == 2
        assert refs["e0"].role == "button"
        assert refs["e1"].role == "heading"
        assert enhanced[2].ref_id is None

    def test_enhance_full_scope(self) -> None:
        """Test enhancement with full scope."""
        nodes = [
            AriaNode(role="button", name="Submit", indent=0),
            AriaNode(role="generic", name="wrapper", indent=0),
        ]

        enhanced, refs = enhance_aria_tree(nodes, scope="full")

        assert len(refs) == 2
        assert enhanced[0].ref_id == "e0"
        assert enhanced[1].ref_id == "e1"

    def test_nth_deduplication(self) -> None:
        """Test nth removal for unique elements."""
        nodes = [
            AriaNode(role="button", name="Submit", indent=0),
            AriaNode(role="button", name="Submit", indent=0),  # duplicate
            AriaNode(role="link", name="Home", indent=0),  # unique
        ]

        _, refs = enhance_aria_tree(nodes, scope="interactive")

        assert refs["e0"].nth == 0  # first duplicate has nth
        assert refs["e1"].nth == 1  # second duplicate has nth
        assert refs["e2"].nth is None  # unique element, no nth

    def test_nth_deduplication_many(self) -> None:
        """Test nth assignment for 5+ duplicate elements."""
        nodes = [AriaNode(role="button", name="Delete", indent=0) for _ in range(5)]

        _, refs = enhance_aria_tree(nodes, scope="interactive")

        assert len(refs) == 5
        for i in range(5):
            assert refs[f"e{i}"].nth == i
            assert refs[f"e{i}"].role == "button"
            assert refs[f"e{i}"].name == "Delete"

    def test_nth_deduplication_nested(self) -> None:
        """Test nth in nested tree structure."""
        nodes = [
            AriaNode(
                role="button",
                name="Submit",
                indent=0,
                children=[
                    AriaNode(role="link", name="Help", indent=1),
                    AriaNode(role="link", name="Help", indent=1),
                ],
            ),
            AriaNode(role="button", name="Submit", indent=0),
        ]

        _, refs = enhance_aria_tree(nodes, scope="interactive")

        assert len(refs) == 4
        assert refs["e0"].nth == 0
        assert refs["e0"].role == "button"
        assert refs["e0"].name == "Submit"
        assert refs["e1"].nth == 0
        assert refs["e1"].role == "link"
        assert refs["e1"].name == "Help"
        assert refs["e2"].nth == 1
        assert refs["e2"].role == "link"
        assert refs["e2"].name == "Help"
        assert refs["e3"].nth == 1
        assert refs["e3"].role == "button"
        assert refs["e3"].name == "Submit"

    def test_nth_mixed_duplicate_unique(self) -> None:
        """Test nth assignment for mixed duplicate and unique elements."""
        nodes = [
            AriaNode(role="button", name="Submit", indent=0),
            AriaNode(role="button", name="Submit", indent=0),
            AriaNode(role="button", name="Submit", indent=0),
            AriaNode(role="button", name="Cancel", indent=0),
            AriaNode(role="button", name="Reset", indent=0),
        ]

        _, refs = enhance_aria_tree(nodes, scope="interactive")

        assert len(refs) == 5
        assert refs["e0"].nth == 0
        assert refs["e0"].name == "Submit"
        assert refs["e1"].nth == 1
        assert refs["e1"].name == "Submit"
        assert refs["e2"].nth == 2
        assert refs["e2"].name == "Submit"
        assert refs["e3"].nth is None
        assert refs["e3"].name == "Cancel"
        assert refs["e4"].nth is None
        assert refs["e4"].name == "Reset"

    def test_nth_deep_nested_structure(self) -> None:
        """Test nth assignment in 3+ layer nested structure."""
        nodes = [
            AriaNode(
                role="navigation",
                name="Main Nav",
                indent=0,
                children=[
                    AriaNode(
                        role="list",
                        name="Menu",
                        indent=1,
                        children=[
                            AriaNode(role="link", name="Home", indent=2),
                            AriaNode(role="link", name="Home", indent=2),
                            AriaNode(
                                role="listitem",
                                name="Dropdown",
                                indent=2,
                                children=[
                                    AriaNode(role="link", name="Settings", indent=3),
                                    AriaNode(role="link", name="Settings", indent=3),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ]

        _, refs = enhance_aria_tree(nodes, scope="interactive")

        assert len(refs) >= 4
        home_refs = [r for r in refs.values() if r.name == "Home"]
        assert len(home_refs) == 2
        assert home_refs[0].nth == 0
        assert home_refs[1].nth == 1

        settings_refs = [r for r in refs.values() if r.name == "Settings"]
        assert len(settings_refs) == 2
        assert settings_refs[0].nth == 0
        assert settings_refs[1].nth == 1

    def test_nth_extreme_duplicates(self) -> None:
        """Test nth with 1000 duplicate elements."""
        nodes = [AriaNode(role="button", name="Action", indent=0) for _ in range(1000)]

        _, refs = enhance_aria_tree(nodes, scope="interactive")

        assert len(refs) == 1000
        for i in range(1000):
            assert refs[f"e{i}"].nth == i
            assert refs[f"e{i}"].role == "button"
            assert refs[f"e{i}"].name == "Action"

    def test_semantic_position_with_bbox(self) -> None:
        """Test semantic position calculation from bbox data."""
        nodes = [AriaNode(role="button", name="Top Left", indent=0)]

        bbox_map = {
            "button:Top Left": {
                "x": 10,
                "y": 10,
                "width": 100,
                "height": 50,
                "centerX": 60,
                "centerY": 35,
                "viewport": {"width": 1920, "height": 1080},
            }
        }

        enhanced, refs = enhance_aria_tree(nodes, scope="interactive", bbox_map=bbox_map)

        assert enhanced[0].position == "at top-left"
        assert refs["e0"].position == "at top-left"
        assert refs["e0"].bbox is not None

    def test_compact_mode_skip_unnamed_structural(self) -> None:
        """Test compact mode skips unnamed structural elements."""
        nodes = [
            AriaNode(role="generic", name="", indent=0),  # unnamed structural
            AriaNode(role="button", name="Click", indent=0),
        ]

        _enhanced, refs = enhance_aria_tree(nodes, scope="full", compact=True)

        # In compact mode with full scope, unnamed structural should not get ref
        assert len(refs) == 1
        assert refs["e0"].role == "button"

    def test_bbox_map_missing_key(self) -> None:
        """Test handling missing bbox keys gracefully."""
        nodes = [AriaNode(role="button", name="Submit", indent=0)]

        bbox_map = {"link:Home": {"x": 0, "y": 0, "width": 100, "height": 50, "centerX": 50, "centerY": 25}}

        enhanced, _refs = enhance_aria_tree(nodes, scope="interactive", bbox_map=bbox_map)

        assert enhanced[0].bbox is None
        assert enhanced[0].position is None

    def test_nested_tree_enhancement(self) -> None:
        """Test enhancement of nested tree structure."""
        nodes = [
            AriaNode(
                role="navigation",
                name="Main Nav",
                children=[
                    AriaNode(role="button", name="Menu", indent=1),
                    AriaNode(role="link", name="About", indent=1),
                ],
                indent=0,
            )
        ]

        enhanced, refs = enhance_aria_tree(nodes, scope="content")

        assert len(refs) == 3  # nav + button + link
        assert enhanced[0].ref_id == "e0"
        assert enhanced[0].children[0].ref_id == "e1"
        assert enhanced[0].children[1].ref_id == "e2"

    def test_empty_tree(self) -> None:
        """Test enhancement of empty tree."""
        enhanced, refs = enhance_aria_tree([], scope="interactive")

        assert len(enhanced) == 0
        assert len(refs) == 0

    def test_bbox_viewport_not_dict(self) -> None:
        """测试viewport不是dict时使用默认值（覆盖line 191）"""
        nodes = [AriaNode(role="button", name="Submit", indent=0)]

        bbox_map = {
            "button:Submit": {
                "x": 100,
                "y": 50,
                "width": 80,
                "height": 30,
                "centerX": 140,
                "centerY": 65,
                "viewport": None,  # Not a dict, should trigger line 191
            }
        }

        _enhanced, refs = enhance_aria_tree(nodes, scope="interactive", bbox_map=bbox_map)

        assert len(refs) == 1
        assert refs["e0"].bbox is not None
        assert refs["e0"].bbox.viewport_width == 1920
        assert refs["e0"].bbox.viewport_height == 1080

    def test_content_only_scope(self) -> None:
        """Test content-only scope filters out interactive elements."""
        nodes = [
            AriaNode(role="button", name="Submit", indent=0),  # interactive, should be filtered
            AriaNode(role="heading", name="Title", indent=0),  # content, should get ref
            AriaNode(role="article", name="Main", indent=0),  # content, should get ref
            AriaNode(role="generic", name="", indent=0),  # structural, should be filtered
        ]

        enhanced, refs = enhance_aria_tree(nodes, scope="content-only")

        assert len(refs) == 2
        assert refs["e0"].role == "heading"
        assert refs["e1"].role == "article"
        assert enhanced[0].ref_id is None  # button filtered
        assert enhanced[3].ref_id is None  # generic filtered

    def test_content_roles_coverage(self) -> None:
        """Test all 21 CONTENT_ROLES get refs in content-only scope."""
        nodes = [
            # Document structure (9)
            AriaNode(role="heading", name="H1", indent=0),
            AriaNode(role="article", name="Post", indent=0),
            AriaNode(role="section", name="Intro", indent=0),
            AriaNode(role="region", name="Main", indent=0),
            AriaNode(role="main", name="Content", indent=0),
            AriaNode(role="navigation", name="Nav", indent=0),
            AriaNode(role="banner", name="Header", indent=0),
            AriaNode(role="contentinfo", name="Footer", indent=0),
            AriaNode(role="complementary", name="Sidebar", indent=0),
            # Table content (4)
            AriaNode(role="cell", name="A1", indent=0),
            AriaNode(role="gridcell", name="B2", indent=0),
            AriaNode(role="columnheader", name="Name", indent=0),
            AriaNode(role="rowheader", name="Row1", indent=0),
            # List content (1)
            AriaNode(role="listitem", name="Item", indent=0),
            # Media content (2)
            AriaNode(role="img", name="Logo", indent=0),
            AriaNode(role="figure", name="Chart", indent=0),
            # Semantic content (5)
            AriaNode(role="term", name="API", indent=0),
            AriaNode(role="definition", name="Interface", indent=0),
            AriaNode(role="blockquote", name="Quote", indent=0),
            AriaNode(role="code", name="snippet", indent=0),
            AriaNode(role="note", name="Tip", indent=0),
        ]

        _enhanced, refs = enhance_aria_tree(nodes, scope="content-only")

        assert len(refs) == 21
        expected_roles = {
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
        }
        actual_roles = {ref.role for ref in refs.values()}
        assert actual_roles == expected_roles

    def test_scope_filtering_boundaries(self) -> None:
        """Test scope filtering boundaries for all three scopes."""
        nodes = [
            AriaNode(role="button", name="Click", indent=0),  # interactive
            AriaNode(role="heading", name="Title", indent=0),  # content
            AriaNode(role="generic", name="wrapper", indent=0),  # structural
        ]

        # interactive scope: only button
        _, refs_interactive = enhance_aria_tree(nodes, scope="interactive")
        assert len(refs_interactive) == 1
        assert refs_interactive["e0"].role == "button"

        # content-only scope: only heading
        _, refs_content_only = enhance_aria_tree(nodes, scope="content-only")
        assert len(refs_content_only) == 1
        assert refs_content_only["e0"].role == "heading"

        # content scope: button + heading
        _, refs_content = enhance_aria_tree(nodes, scope="content")
        assert len(refs_content) == 2
        assert refs_content["e0"].role == "button"
        assert refs_content["e1"].role == "heading"

        # full scope: all three
        _, refs_full = enhance_aria_tree(nodes, scope="full")
        assert len(refs_full) == 3

    def test_new_content_roles_in_nested_structure(self) -> None:
        """Test new CONTENT_ROLES (img/code/blockquote) in nested structure."""
        nodes = [
            AriaNode(
                role="article",
                name="Blog Post",
                children=[
                    AriaNode(role="heading", name="Title", indent=1),
                    AriaNode(role="img", name="Hero Image", indent=1),
                    AriaNode(role="code", name="Example", indent=1),
                    AriaNode(role="blockquote", name="Quote", indent=1),
                ],
                indent=0,
            )
        ]

        _enhanced, refs = enhance_aria_tree(nodes, scope="content-only")

        assert len(refs) == 5
        assert refs["e0"].role == "article"
        assert refs["e1"].role == "heading"
        assert refs["e2"].role == "img"
        assert refs["e3"].role == "code"
        assert refs["e4"].role == "blockquote"

    def test_nth_empty_name(self) -> None:
        """Negative Test: Elements with empty name should still get nth correctly."""
        nodes = [
            AriaNode(role="button", name="", indent=0),
            AriaNode(role="button", name="", indent=0),
            AriaNode(role="button", name="Submit", indent=0),
        ]

        _, refs = enhance_aria_tree(nodes, scope="interactive")

        assert len(refs) == 3
        assert refs["e0"].nth == 0
        assert refs["e1"].nth == 1
        assert refs["e2"].nth is None

    def test_nth_special_characters_in_name(self) -> None:
        """Negative Test: Elements with special characters in name."""
        nodes = [
            AriaNode(role="button", name='Click "Me"', indent=0),
            AriaNode(role="button", name='Click "Me"', indent=0),
            AriaNode(role="button", name="<script>alert('xss')</script>", indent=0),
        ]

        _, refs = enhance_aria_tree(nodes, scope="interactive")

        assert len(refs) == 3
        assert refs["e0"].nth == 0
        assert refs["e1"].nth == 1
        assert refs["e2"].nth is None

    def test_nth_unicode_characters(self) -> None:
        """Negative Test: Elements with Unicode characters (Chinese, Emoji)."""
        nodes = [
            AriaNode(role="button", name="提交", indent=0),
            AriaNode(role="button", name="提交", indent=0),
            AriaNode(role="button", name=" Launch", indent=0),
            AriaNode(role="button", name=" Launch", indent=0),
        ]

        _, refs = enhance_aria_tree(nodes, scope="interactive")

        assert len(refs) == 4
        assert refs["e0"].nth == 0
        assert refs["e1"].nth == 1
        assert refs["e2"].nth == 0
        assert refs["e3"].nth == 1

    def test_nth_very_long_name(self) -> None:
        """Negative Test: Elements with very long names (1000+ chars)."""
        long_name = "A" * 1000
        nodes = [
            AriaNode(role="button", name=long_name, indent=0),
            AriaNode(role="button", name=long_name, indent=0),
        ]

        _, refs = enhance_aria_tree(nodes, scope="interactive")

        assert len(refs) == 2
        assert refs["e0"].nth == 0
        assert refs["e1"].nth == 1
        assert refs["e0"].name == long_name
        assert refs["e1"].name == long_name

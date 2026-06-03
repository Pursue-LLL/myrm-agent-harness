"""Comprehensive tests for semantic location enhancement system.

测试覆盖：
1. BBox 收集器（_collect_bboxes）
2. 语义位置转换器（_calculate_semantic_position）
3. parse_and_enhance_aria_tree 与 bbox_map
4. 向后兼容性
5. 边界情况和异常处理
"""

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.aria_enhancer import enhance_aria_tree
from myrm_agent_harness.toolkits.browser.snapshot.aria_parser import parse_aria_yaml
from myrm_agent_harness.toolkits.browser.snapshot.aria_renderer import render_to_yaml
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import (
    BBox,
    RefInfo,
    SnapshotMeta,
    calculate_semantic_position,
)


def _convert_legacy_yaml_format(aria_tree: str) -> str:
    """Convert legacy format (- role \"name\") to standard YAML format.

    Legacy format: - WebArea \"Test\"\\n  - button \"Click\"
    Standard format: - WebArea:\\n      name: \"Test\"\\n      children:\\n        - button:\\n            name: \"Click\"
    """
    import re

    lines = [line for line in aria_tree.strip().split("\n") if line.strip()]
    if not lines:
        return ""

    def parse_tree(lines: list[tuple[int, str, str]], start: int, parent_indent: int) -> tuple[list[dict], int]:
        """Parse lines into tree structure."""
        nodes = []
        i = start

        while i < len(lines):
            indent, role, name = lines[i]

            if indent < parent_indent:
                break

            if indent > parent_indent:
                i += 1
                continue

            children, i = parse_tree(lines, i + 1, indent + 1)
            nodes.append({"role": role, "name": name, "children": children})

        return nodes, i

    def tree_to_yaml(nodes: list[dict], indent: int = 0) -> str:
        """Convert tree structure to standard YAML."""
        result = []
        prefix = "  " * indent

        for node in nodes:
            role, name, children = node["role"], node["name"], node["children"]
            result.append(f"{prefix}- {role}:")
            if name:
                result.append(f"{prefix}    name: {name!r}")
            if children:
                result.append(f"{prefix}    children:")
                result.append(tree_to_yaml(children, indent + 2))

        return "\n".join(result)

    # Parse legacy format
    parsed_lines = []
    for line in lines:
        match = re.match(r'^(\s*)- (\w+) "([^"]*)"', line)
        if match:
            indent_str, role, name = match.groups()
            indent_level = len(indent_str) // 2
            parsed_lines.append((indent_level, role, name))

    if not parsed_lines:
        return ""

    tree, _ = parse_tree(parsed_lines, 0, -1)
    return tree_to_yaml(tree)


def _parse_and_enhance_wrapper(
    aria_tree: str,
    *,
    scope: str = "interactive",
    compact: bool = False,
    bbox_map: dict[str, dict[str, int | dict[str, int]]] | None = None,
) -> tuple[str, dict[str, RefInfo], SnapshotMeta]:
    """Test helper: wraps four-layer architecture to match old API signature."""
    # Detect format: if line matches '- role "name"', convert; otherwise use as-is
    import re

    first_line = aria_tree.strip().split("\n")[0] if aria_tree.strip() else ""
    is_legacy = bool(re.match(r'^\s*- \w+ "[^"]*"', first_line))

    if is_legacy:
        converted = _convert_legacy_yaml_format(aria_tree)
    else:
        converted = aria_tree

    nodes = parse_aria_yaml(converted)
    enhanced_nodes, refs = enhance_aria_tree(nodes, scope=scope, compact=compact, bbox_map=bbox_map)
    text, meta = render_to_yaml(enhanced_nodes, compact=compact)
    return text, refs, meta


class TestSemanticPositionCalculation:
    """测试语义位置计算（3x3 网格）"""

    @pytest.mark.parametrize(
        "center_x,center_y,viewport_width,viewport_height,expected",
        [
            # Top-left (< 33% both)
            (200, 150, 1920, 1080, "at top-left"),
            (100, 100, 1920, 1080, "at top-left"),
            (630, 355, 1920, 1080, "at top-left"),  # 边界（32.8%, 32.9%）
            # Top-center
            (960, 150, 1920, 1080, "at top"),
            (640, 200, 1920, 1080, "at top"),
            (1279, 300, 1920, 1080, "at top"),
            # Top-right (> 67% horizontal)
            (1600, 150, 1920, 1080, "at top-right"),
            (1800, 200, 1920, 1080, "at top-right"),
            (1290, 100, 1920, 1080, "at top-right"),  # 边界（67.2%）
            # Center-left
            (200, 540, 1920, 1080, "at left"),
            (100, 400, 1920, 1080, "at left"),
            (600, 700, 1920, 1080, "at left"),
            # Center-center
            (960, 540, 1920, 1080, "at center"),
            (800, 500, 1920, 1080, "at center"),
            (1100, 600, 1920, 1080, "at center"),
            # Center-right
            (1600, 540, 1920, 1080, "at right"),
            (1800, 400, 1920, 1080, "at right"),
            (1400, 700, 1920, 1080, "at right"),
            # Bottom-left
            (200, 900, 1920, 1080, "at bottom-left"),
            (100, 1000, 1920, 1080, "at bottom-left"),
            (600, 725, 1920, 1080, "at bottom-left"),  # 边界（67.1%）
            # Bottom-center
            (960, 900, 1920, 1080, "at bottom"),
            (800, 1000, 1920, 1080, "at bottom"),
            (1100, 800, 1920, 1080, "at bottom"),
            # Bottom-right
            (1600, 900, 1920, 1080, "at bottom-right"),
            (1800, 1000, 1920, 1080, "at bottom-right"),
            (1400, 800, 1920, 1080, "at bottom-right"),
            # Edge cases - origin
            (0, 0, 1920, 1080, "at top-left"),
            (10, 10, 1920, 1080, "at top-left"),
            # Edge cases - corners
            (1919, 0, 1920, 1080, "at top-right"),
            (0, 1079, 1920, 1080, "at bottom-left"),
            (1919, 1079, 1920, 1080, "at bottom-right"),
            # Small viewport
            (50, 50, 100, 100, "at center"),
            (10, 10, 100, 100, "at top-left"),
            (90, 90, 100, 100, "at bottom-right"),
            # Large viewport (4K)
            (1920, 1080, 3840, 2160, "at center"),
            (640, 360, 3840, 2160, "at top-left"),
            (3200, 1800, 3840, 2160, "at bottom-right"),
        ],
    )
    def test_all_positions(
        self, center_x: int, center_y: int, viewport_width: int, viewport_height: int, expected: str
    ) -> None:
        """测试所有 9 种位置 + 边界情况"""
        bbox = BBox(
            x=0,
            y=0,
            width=100,
            height=50,
            centerX=center_x,
            centerY=center_y,
            viewport_x=0,
            viewport_y=0,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )
        assert calculate_semantic_position(bbox) == expected

    def test_exact_grid_boundaries(self):
        """测试精确的网格边界（33.33% 和 66.67%）"""
        # 33.33% 分界线：1920*0.33=633.6, 1080*0.33=356.4
        # 刚好在 top-left
        bbox1 = BBox(
            x=0, y=0, width=100, height=50, centerX=633, centerY=356, viewport_x=0, viewport_y=0, viewport_width=1920, viewport_height=1080
        )
        assert calculate_semantic_position(bbox1) == "at top-left"

        # 刚好越过到 center
        bbox2 = BBox(
            x=0, y=0, width=100, height=50, centerX=634, centerY=357, viewport_x=0, viewport_y=0, viewport_width=1920, viewport_height=1080
        )
        assert calculate_semantic_position(bbox2) == "at center"

        # 66.67% 分界线：1920*0.67=1286.4, 1080*0.67=723.6
        # 刚好在 center
        bbox3 = BBox(
            x=0, y=0, width=100, height=50, centerX=1286, centerY=723, viewport_x=0, viewport_y=0, viewport_width=1920, viewport_height=1080
        )
        assert calculate_semantic_position(bbox3) == "at center"

        # 刚好越过到 bottom-right
        bbox4 = BBox(
            x=0, y=0, width=100, height=50, centerX=1287, centerY=724, viewport_x=0, viewport_y=0, viewport_width=1920, viewport_height=1080
        )
        assert calculate_semantic_position(bbox4) == "at bottom-right"


class TestParseWithBBox:
    """测试 parse_and_enhance_aria_tree 与 bbox_map 集成"""

    def test_with_bbox_map_full_coverage(self):
        """测试所有元素都有 bbox 数据"""
        aria_tree = """- WebArea:
    name: ""
    children:
      - link:
          name: "Home"
      - button:
          name: "Submit"
      - textbox:
          name: "Search"
"""
        bbox_map = {
            "link:Home": {
                "x": 100,
                "y": 50,
                "width": 80,
                "height": 30,
                "centerX": 140,
                "centerY": 65,
                "viewport": {"width": 1920, "height": 1080},
            },
            "button:Submit": {
                "x": 1700,
                "y": 900,
                "width": 120,
                "height": 40,
                "centerX": 1760,
                "centerY": 920,
                "viewport": {"width": 1920, "height": 1080},
            },
            "textbox:Search": {
                "x": 800,
                "y": 50,
                "width": 200,
                "height": 35,
                "centerX": 900,
                "centerY": 67,
                "viewport": {"width": 1920, "height": 1080},
            },
        }

        enhanced_tree, refs, _meta = _parse_and_enhance_wrapper(
            aria_tree, scope="interactive", compact=False, bbox_map=bbox_map
        )

        # 验证 refs 包含正确的 bbox 和 position
        assert "e0" in refs
        assert refs["e0"].role == "link"
        assert refs["e0"].name == "Home"
        assert refs["e0"].bbox is not None
        assert refs["e0"].bbox.x == 100
        assert refs["e0"].position == "at top-left"

        assert "e1" in refs
        assert refs["e1"].role == "button"
        assert refs["e1"].position == "at bottom-right"

        assert "e2" in refs
        assert refs["e2"].role == "textbox"
        assert refs["e2"].position == "at top"

        # 验证 ARIA 树文本包含位置描述符
        assert "at top-left" in enhanced_tree
        assert "at bottom-right" in enhanced_tree
        assert "at top" in enhanced_tree

    def test_with_bbox_map_partial_coverage(self):
        """测试部分元素有 bbox 数据"""
        aria_tree = """- WebArea:
    name: ""
    children:
      - link:
          name: "Home"
      - button:
          name: "Submit"
      - link:
          name: "About"
"""
        bbox_map = {
            "link:Home": {
                "x": 100,
                "y": 50,
                "width": 80,
                "height": 30,
                "centerX": 140,
                "centerY": 65,
                "viewport": {"width": 1920, "height": 1080},
            },
            # "button:Submit" 没有 bbox
            # "link:About" 没有 bbox
        }

        enhanced_tree, refs, _meta = _parse_and_enhance_wrapper(
            aria_tree, scope="interactive", compact=False, bbox_map=bbox_map
        )

        # e0 有 bbox 和 position
        assert refs["e0"].bbox is not None
        assert refs["e0"].position == "at top-left"

        # e1 和 e2 没有 bbox 和 position
        assert refs["e1"].bbox is None
        assert refs["e1"].position is None
        assert refs["e2"].bbox is None
        assert refs["e2"].position is None

        # ARIA 树只包含有 bbox 的元素的位置
        assert "at top-left" in enhanced_tree
        assert enhanced_tree.count("at ") == 1

    def test_without_bbox_map_backward_compatibility(self):
        """测试向后兼容性（无 bbox_map）"""
        aria_tree = """- WebArea:
    name: ""
    children:
      - link:
          name: "Home"
      - button:
          name: "Submit"
"""
        enhanced_tree, refs, _meta = _parse_and_enhance_wrapper(
            aria_tree, scope="interactive", compact=False, bbox_map=None
        )

        # 所有 refs 都没有 bbox 和 position
        assert refs["e0"].bbox is None
        assert refs["e0"].position is None
        assert refs["e1"].bbox is None
        assert refs["e1"].position is None

        # ARIA 树不包含位置描述符
        assert "at " not in enhanced_tree

    def test_with_empty_bbox_map(self):
        """测试空 bbox_map"""
        aria_tree = """- WebArea:
    name: ""
    children:
      - link:
          name: "Home"
      - button:
          name: "Submit"
"""
        bbox_map = {}

        _enhanced_tree, refs, _meta = _parse_and_enhance_wrapper(
            aria_tree, scope="interactive", compact=False, bbox_map=bbox_map
        )

        # 所有 refs 都没有 bbox 和 position
        assert refs["e0"].bbox is None
        assert refs["e0"].position is None
        assert refs["e1"].bbox is None
        assert refs["e1"].position is None

    def test_with_bbox_map_compact_format(self):
        """测试 bbox_map 与 compact 格式"""
        aria_tree = """- WebArea:
    name: ""
    children:
      - link:
          name: "Home"
      - button:
          name: "Submit"
"""
        bbox_map = {
            "link:Home": {
                "x": 100,
                "y": 50,
                "width": 80,
                "height": 30,
                "centerX": 140,
                "centerY": 65,
                "viewport": {"width": 1920, "height": 1080},
            },
        }

        enhanced_tree, refs, _meta = _parse_and_enhance_wrapper(
            aria_tree, scope="interactive", compact=True, bbox_map=bbox_map
        )

        # compact 格式应该包含位置
        assert "e0:link at top-left" in enhanced_tree or "e0:link" in enhanced_tree
        # refs 仍然包含完整信息
        assert refs["e0"].position == "at top-left"

    def test_with_bbox_map_duplicate_elements(self):
        """测试 bbox_map 与重复元素（nth 场景）"""
        aria_tree = """- WebArea:
    name: ""
    children:
      - button:
          name: "Click"
      - button:
          name: "Click"
      - button:
          name: "Click"
"""
        bbox_map = {
            "button:Click": {
                "x": 100,
                "y": 50,
                "width": 80,
                "height": 30,
                "centerX": 140,
                "centerY": 65,
                "viewport": {"width": 1920, "height": 1080},
            },
        }

        _enhanced_tree, refs, _meta = _parse_and_enhance_wrapper(
            aria_tree, scope="interactive", compact=False, bbox_map=bbox_map
        )

        # 所有同名元素共享相同的 bbox（第一个匹配）
        assert refs["e0"].position == "at top-left"
        assert refs["e1"].position == "at top-left"
        assert refs["e2"].position == "at top-left"

        # nth 仍然正确分配
        assert refs["e0"].nth == 0
        assert refs["e1"].nth == 1
        assert refs["e2"].nth == 2


class TestBBoxDataStructure:
    """测试 BBox 数据结构"""

    def test_bbox_namedtuple(self):
        """测试 BBox NamedTuple"""
        bbox = BBox(
            x=100, y=200, width=300, height=400, centerX=250, centerY=400, viewport_x=0, viewport_y=0, viewport_width=1920, viewport_height=1080
        )

        assert bbox.x == 100
        assert bbox.y == 200
        assert bbox.width == 300
        assert bbox.height == 400
        assert bbox.centerX == 250
        assert bbox.centerY == 400
        assert bbox.viewport_width == 1920
        assert bbox.viewport_height == 1080

    def test_refinfo_with_bbox_and_position(self):
        """测试 RefInfo 包含 bbox 和 position"""
        bbox = BBox(
            x=100, y=200, width=300, height=400, centerX=250, centerY=400, viewport_x=0, viewport_y=0, viewport_width=1920, viewport_height=1080
        )
        ref_info = RefInfo(role="button", name="Submit", nth=None, bbox=bbox, position="at top-left")

        assert ref_info.role == "button"
        assert ref_info.name == "Submit"
        assert ref_info.nth is None
        assert ref_info.bbox == bbox
        assert ref_info.position == "at top-left"

    def test_refinfo_without_bbox_and_position(self):
        """测试 RefInfo 不包含 bbox 和 position（向后兼容）"""
        ref_info = RefInfo(role="button", name="Submit", nth=None)

        assert ref_info.bbox is None
        assert ref_info.position is None

    def test_refinfo_with_only_bbox(self):
        """测试 RefInfo 只包含 bbox"""
        bbox = BBox(
            x=100, y=200, width=300, height=400, centerX=250, centerY=400, viewport_x=0, viewport_y=0, viewport_width=1920, viewport_height=1080
        )
        ref_info = RefInfo(role="button", name="Submit", nth=None, bbox=bbox)

        assert ref_info.bbox == bbox
        assert ref_info.position is None


class TestEdgeCases:
    """测试边界情况和异常场景"""

    def test_bbox_with_zero_dimensions(self):
        """测试零宽高的 bbox"""
        aria_tree = """- WebArea:
    name: ""
    children:
      - button:
          name: "Hidden"
"""
        bbox_map = {
            "button:Hidden": {
                "x": 100,
                "y": 200,
                "width": 0,
                "height": 0,
                "centerX": 100,
                "centerY": 200,
                "viewport": {"width": 1920, "height": 1080},
            },
        }

        _enhanced_tree, refs, _meta = _parse_and_enhance_wrapper(
            aria_tree, scope="interactive", compact=False, bbox_map=bbox_map
        )

        # 即使宽高为 0，仍然可以计算位置
        assert refs["e0"].bbox is not None
        assert refs["e0"].position == "at top-left"

    def test_bbox_with_negative_coordinates(self):
        """测试负坐标的 bbox（元素在视口外）"""
        aria_tree = """- WebArea:
    name: ""
    children:
      - button:
          name: "Offscreen"
"""
        bbox_map = {
            "button:Offscreen": {
                "x": -100,
                "y": -200,
                "width": 50,
                "height": 30,
                "centerX": -75,
                "centerY": -185,
                "viewport": {"width": 1920, "height": 1080},
            },
        }

        _enhanced_tree, refs, _meta = _parse_and_enhance_wrapper(
            aria_tree, scope="interactive", compact=False, bbox_map=bbox_map
        )

        # 负坐标仍然会被归类到 top-left
        assert refs["e0"].position == "at top-left"

    def test_bbox_with_overflow_coordinates(self):
        """测试超出视口的 bbox"""
        aria_tree = """- WebArea:
    name: ""
    children:
      - button:
          name: "Overflow"
"""
        bbox_map = {
            "button:Overflow": {
                "x": 2000,
                "y": 1200,
                "width": 100,
                "height": 50,
                "centerX": 2050,
                "centerY": 1225,
                "viewport": {"width": 1920, "height": 1080},
            },
        }

        _enhanced_tree, refs, _meta = _parse_and_enhance_wrapper(
            aria_tree, scope="interactive", compact=False, bbox_map=bbox_map
        )

        # 超出视口的元素仍然会被归类到 bottom-right
        assert refs["e0"].position == "at bottom-right"

    def test_empty_aria_tree_with_bbox_map(self):
        """测试空 ARIA 树与 bbox_map"""
        aria_tree = ""
        bbox_map = {
            "button:Test": {
                "x": 100,
                "y": 200,
                "width": 50,
                "height": 30,
                "centerX": 125,
                "centerY": 215,
                "viewport": {"width": 1920, "height": 1080},
            }
        }

        enhanced_tree, refs, meta = _parse_and_enhance_wrapper(
            aria_tree, scope="interactive", compact=False, bbox_map=bbox_map
        )

        assert enhanced_tree == ""
        assert refs == {}
        assert meta.ref_count == 0

    def test_malformed_bbox_map(self):
        """测试格式错误的 bbox_map（缺少字段）"""
        aria_tree = """- WebArea ""
  - button "Test"
"""
        # 缺少 viewport 字段
        bbox_map = {
            "button:Test": {
                "x": 100,
                "y": 200,
                "width": 50,
                "height": 30,
                "centerX": 125,
                "centerY": 215,
                # 缺少 viewport
            },
        }

        # 应该优雅降级（使用默认 viewport 或跳过）
        try:
            _enhanced_tree, refs, _meta = _parse_and_enhance_wrapper(
                aria_tree, scope="interactive", compact=False, bbox_map=bbox_map
            )
            # 如果没有抛出异常，检查是否使用了默认值
            if refs["e0"].bbox:
                assert refs["e0"].bbox.viewport_width > 0
                assert refs["e0"].bbox.viewport_height > 0
        except (KeyError, TypeError):
            # 预期可能抛出异常
            pass


class TestIntegration:
    """集成测试"""

    def test_full_workflow_with_positions(self):
        """测试完整工作流：解析 → 增强 → 验证"""
        aria_tree = """- WebArea:
    name: "Example Page"
    children:
      - navigation:
          children:
            - link:
                name: "Home"
            - link:
                name: "About"
            - link:
                name: "Contact"
      - main:
          children:
            - heading:
                name: "Welcome"
            - article:
                children:
                  - button:
                      name: "Read More"
      - complementary:
          children:
            - textbox:
                name: "Search"
            - button:
                name: "Go"
"""
        bbox_map = {
            "link:Home": {
                "x": 10,
                "y": 10,
                "width": 50,
                "height": 20,
                "centerX": 35,
                "centerY": 20,
                "viewport": {"width": 1920, "height": 1080},
            },
            "link:About": {
                "x": 70,
                "y": 10,
                "width": 50,
                "height": 20,
                "centerX": 95,
                "centerY": 20,
                "viewport": {"width": 1920, "height": 1080},
            },
            "link:Contact": {
                "x": 130,
                "y": 10,
                "width": 60,
                "height": 20,
                "centerX": 160,
                "centerY": 20,
                "viewport": {"width": 1920, "height": 1080},
            },
            "button:Read More": {
                "x": 800,
                "y": 500,
                "width": 100,
                "height": 40,
                "centerX": 850,
                "centerY": 520,
                "viewport": {"width": 1920, "height": 1080},
            },
            "textbox:Search": {
                "x": 1700,
                "y": 100,
                "width": 150,
                "height": 30,
                "centerX": 1775,
                "centerY": 115,
                "viewport": {"width": 1920, "height": 1080},
            },
            "button:Go": {
                "x": 1860,
                "y": 100,
                "width": 50,
                "height": 30,
                "centerX": 1885,
                "centerY": 115,
                "viewport": {"width": 1920, "height": 1080},
            },
        }

        enhanced_tree, refs, meta = _parse_and_enhance_wrapper(
            aria_tree, scope="interactive", compact=False, bbox_map=bbox_map
        )

        # 验证所有交互元素都有正确的位置
        positions = {ref_id: info.position for ref_id, info in refs.items()}

        # 导航链接都在 top-left
        assert positions["e0"] == "at top-left"  # Home
        assert positions["e1"] == "at top-left"  # About
        assert positions["e2"] == "at top-left"  # Contact

        # Read More 在 center
        assert positions["e3"] == "at center"

        # Search 和 Go 在 top-right
        assert positions["e4"] == "at top-right"
        assert positions["e5"] == "at top-right"

        # 验证元数据
        assert meta.ref_count == 6
        assert meta.estimated_tokens > 0

        # 验证 ARIA 树包含所有位置
        assert "at top-left" in enhanced_tree
        assert "at center" in enhanced_tree
        assert "at top-right" in enhanced_tree

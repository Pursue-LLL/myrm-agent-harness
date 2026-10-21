"""Comprehensive tests for BBox collector in FrameSnapshot.

测试覆盖：
1. 正常收集 bbox
2. 空 ARIA 树
3. 无匹配元素
4. evaluate 失败降级
5. 超时处理
6. 多种 role 类型
7. 特殊字符处理
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.element_detectors import collect_bboxes


class TestBBoxCollector:
    """测试 collect_bboxes 方法"""

    @pytest.fixture
    def mock_frame(self):
        """Mock Playwright Frame"""
        frame = MagicMock()
        frame.evaluate = AsyncMock()
        return frame

    # 移除 frame_snapshot fixture，直接使用 collect_bboxes 函数

    @pytest.mark.asyncio
    async def test_collect_bboxes_success(self, mock_frame):
        """测试正常收集 bbox"""
        aria_tree = """- WebArea "":
    - link "Home"
    - button "Submit"
"""
        # Mock evaluate 返回
        mock_frame.evaluate.return_value = {
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
        }

        bbox_map = await collect_bboxes(mock_frame, aria_tree)

        # 验证返回正确的 bbox_map
        assert len(bbox_map) == 2
        assert "link:Home" in bbox_map
        assert "button:Submit" in bbox_map
        assert bbox_map["link:Home"]["x"] == 100
        assert bbox_map["button:Submit"]["centerY"] == 920

        # 验证 evaluate 被调用
        mock_frame.evaluate.assert_called_once()
        call_args = mock_frame.evaluate.call_args[0]
        role_name_pairs = call_args[1]

        # 验证传递的 role_name_pairs
        assert len(role_name_pairs) == 2
        assert {"role": "link", "name": "Home"} in role_name_pairs
        assert {"role": "button", "name": "Submit"} in role_name_pairs

    @pytest.mark.asyncio
    async def test_collect_bboxes_empty_aria_tree(self, mock_frame):
        """测试空 ARIA 树"""
        aria_tree = ""

        bbox_map = await collect_bboxes(mock_frame, aria_tree)

        # 应该返回空 dict
        assert bbox_map == {}

        # 不应该调用 evaluate
        mock_frame.evaluate.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_bboxes_no_named_elements(self, mock_frame):
        """测试无命名元素的 ARIA 树"""
        aria_tree = """- WebArea "":
    - generic ""
    - group ""
"""
        bbox_map = await collect_bboxes(mock_frame, aria_tree)

        # 应该返回空 dict（没有命名元素）
        assert bbox_map == {}

        # 不应该调用 evaluate
        mock_frame.evaluate.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_bboxes_evaluate_returns_empty(self, mock_frame):
        """测试 evaluate 返回空对象"""
        aria_tree = """- WebArea "":
    - button "Test"
"""
        mock_frame.evaluate.return_value = {}

        bbox_map = await collect_bboxes(mock_frame, aria_tree)

        # 应该返回空 dict
        assert bbox_map == {}

    @pytest.mark.asyncio
    async def test_collect_bboxes_evaluate_returns_non_dict(self, mock_frame):
        """测试 evaluate 返回非 dict 类型"""
        aria_tree = """- WebArea "":
    - button "Test"
"""
        mock_frame.evaluate.return_value = None

        bbox_map = await collect_bboxes(mock_frame, aria_tree)

        # 应该返回空 dict
        assert bbox_map == {}

    @pytest.mark.asyncio
    async def test_collect_bboxes_evaluate_failure(self, mock_frame):
        """测试 evaluate 失败（优雅降级）"""
        aria_tree = """- WebArea "":
    - button "Test"
"""
        mock_frame.evaluate.side_effect = Exception("Evaluate failed")

        bbox_map = await collect_bboxes(mock_frame, aria_tree)

        # 应该返回空 dict（不抛出异常）
        assert bbox_map == {}

    @pytest.mark.asyncio
    async def test_collect_bboxes_timeout(self, mock_frame):
        """测试 evaluate 超时"""
        aria_tree = """- WebArea "":
    - button "Test"
"""

        async def slow_evaluate(*args, **kwargs):
            await asyncio.sleep(5)
            return {}

        mock_frame.evaluate.side_effect = slow_evaluate

        bbox_map = await collect_bboxes(mock_frame, aria_tree)

        # 应该返回空 dict（超时被捕获）
        assert bbox_map == {}

    @pytest.mark.asyncio
    async def test_collect_bboxes_special_characters_in_name(self, mock_frame):
        """测试名称包含特殊字符"""
        aria_tree = """- WebArea "":
    - button 'Click "Me"!'
    - link "Home & Away"
    - textbox "Search:"
"""
        mock_frame.evaluate.return_value = {
            'button:Click "Me"!': {
                "x": 100,
                "y": 200,
                "width": 80,
                "height": 30,
                "centerX": 140,
                "centerY": 215,
                "viewport": {"width": 1920, "height": 1080},
            },
        }

        bbox_map = await collect_bboxes(mock_frame, aria_tree)

        assert len(bbox_map) == 1
        assert 'button:Click "Me"!' in bbox_map

    @pytest.mark.asyncio
    async def test_collect_bboxes_mixed_roles(self, mock_frame):
        """测试多种 role 类型"""
        aria_tree = """- WebArea "":
    - button "Submit"
    - link "Home"
    - textbox "Search"
    - checkbox "Agree"
    - combobox "Select"
    - slider "Volume"
"""
        mock_frame.evaluate.return_value = {
            "button:Submit": {
                "x": 100,
                "y": 100,
                "width": 50,
                "height": 30,
                "centerX": 125,
                "centerY": 115,
                "viewport": {"width": 1920, "height": 1080},
            },
            "link:Home": {
                "x": 200,
                "y": 100,
                "width": 50,
                "height": 30,
                "centerX": 225,
                "centerY": 115,
                "viewport": {"width": 1920, "height": 1080},
            },
            "textbox:Search": {
                "x": 300,
                "y": 100,
                "width": 150,
                "height": 30,
                "centerX": 375,
                "centerY": 115,
                "viewport": {"width": 1920, "height": 1080},
            },
        }

        bbox_map = await collect_bboxes(mock_frame, aria_tree)

        # 验证所有 role 都被正确提取
        assert len(bbox_map) == 3
        assert "button:Submit" in bbox_map
        assert "link:Home" in bbox_map
        assert "textbox:Search" in bbox_map

        # 验证传递给 evaluate 的 pairs
        call_args = mock_frame.evaluate.call_args[0]
        role_name_pairs = call_args[1]
        assert len(role_name_pairs) == 6


class TestBBoxCollectorScript:
    """测试 BBOX_COLLECTOR_SCRIPT 逻辑（通过验证调用参数）"""

    @pytest.mark.asyncio
    async def test_script_receives_role_name_pairs(self):
        """验证脚本接收正确的 role_name_pairs 格式"""

        mock_frame = MagicMock()
        mock_frame.evaluate = AsyncMock(return_value={})

        # No longer needed

        aria_tree = """- WebArea "":
    - button "Test"
    - link "Home"
"""
        await collect_bboxes(mock_frame, aria_tree)

        # 验证脚本和参数
        call_args = mock_frame.evaluate.call_args[0]
        script = call_args[0]
        role_name_pairs = call_args[1]

        # 验证脚本是 BBOX_COLLECTOR_SCRIPT
        assert "getBoundingClientRect" in script
        assert "viewport" in script

        # 验证 role_name_pairs 格式
        assert isinstance(role_name_pairs, list)
        assert len(role_name_pairs) == 2
        assert role_name_pairs[0] == {"role": "button", "name": "Test"}
        assert role_name_pairs[1] == {"role": "link", "name": "Home"}

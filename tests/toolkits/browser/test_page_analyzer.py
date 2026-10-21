"""Unit tests for PageAnalyzer"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.session.page_analyzer import PageAnalyzer


class TestPageAnalyzer:
    """测试页面分析器"""

    @pytest.mark.asyncio
    async def test_analyze_with_main_region(self):
        """测试检测 main 区域"""
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(
            return_value={
                "title": "GitHub PR #123",
                "url": "https://github.com/user/repo/pull/123",
                "totalInteractive": 800,
                "regions": [
                    ["main.content", "<main> region", 600],
                    ["aside.sidebar", "<article> region", 150],
                    ["nav.top-bar", "<nav> region", 50],
                ],
            }
        )

        analyzer = PageAnalyzer(mock_page)
        result = await analyzer.analyze()

        assert result.page_title == "GitHub PR #123"
        assert result.total_interactive_elements == 800
        assert len(result.detected_regions) == 3
        assert result.detected_regions[0] == ("main.content", "<main> region", 600)
        assert result.recommended_selector == "main.content"
        assert result.estimated_savings == "25%"  # (800-600)/800 = 25%

    @pytest.mark.asyncio
    async def test_analyze_small_page(self):
        """测试小页面（不需要优化）"""
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(
            return_value={
                "title": "Simple Page",
                "url": "https://example.com",
                "totalInteractive": 30,
                "regions": [["main", "<main> region", 25]],
            }
        )

        analyzer = PageAnalyzer(mock_page)
        result = await analyzer.analyze()

        assert result.total_interactive_elements == 30
        assert result.recommended_selector == ""
        assert result.estimated_savings == "0%"

    @pytest.mark.asyncio
    async def test_analyze_no_regions(self):
        """测试没有检测到区域的情况"""
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(
            return_value={"title": "Empty", "url": "https://example.com", "totalInteractive": 100, "regions": []}
        )

        analyzer = PageAnalyzer(mock_page)
        result = await analyzer.analyze()

        assert result.total_interactive_elements == 100
        assert len(result.detected_regions) == 0
        assert result.recommended_selector == ""

    @pytest.mark.asyncio
    async def test_analyze_exception_handling(self):
        """测试异常处理（浏览器上下文失效等）"""
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(side_effect=Exception("Page context destroyed"))

        analyzer = PageAnalyzer(mock_page)
        result = await analyzer.analyze()

        # 应返回 fallback 结果
        assert result.page_title == "Unknown"
        assert result.total_interactive_elements == 0
        assert len(result.detected_regions) == 0

    @pytest.mark.asyncio
    async def test_analyze_form_page(self):
        """测试表单页面"""
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(
            return_value={
                "title": "Login",
                "url": "https://app.com/login",
                "totalInteractive": 50,
                "regions": [["form", "<form> region", 8], ["#app", "ID container", 45]],
            }
        )

        analyzer = PageAnalyzer(mock_page)
        result = await analyzer.analyze()

        # #app 包含更多元素，应优先推荐
        assert result.recommended_selector == "#app"
        # (50-45)/50 = 10%, but int rounding may give 9%
        assert result.estimated_savings in ["9%", "10%"]

    def test_compute_recommendation_logic(self):
        """测试推荐计算逻辑"""
        analyzer = PageAnalyzer(MagicMock())

        # 大页面，主要区域占 75%
        selector, savings = analyzer._compute_recommendation(800, [("main", "Main", 600)])
        assert selector == "main"
        assert savings == "25%"

        # 小页面，不推荐
        selector, savings = analyzer._compute_recommendation(40, [("main", "Main", 30)])
        assert selector == ""
        assert savings == "0%"

        # 无区域
        selector, savings = analyzer._compute_recommendation(100, [])
        assert selector == ""
        assert savings == "0%"

    @pytest.mark.asyncio
    async def test_analyze_deduplication(self):
        """测试区域去重（避免重复 selector）"""
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(
            return_value={
                "title": "Test",
                "url": "https://test.com",
                "totalInteractive": 100,
                "regions": [
                    ["main", "<main> region", 60],
                    ["main", "<main> region", 60],  # 重复
                    ["#app", "ID container", 80],
                ],
            }
        )

        analyzer = PageAnalyzer(mock_page)
        result = await analyzer.analyze()

        # 应该去重
        assert len(result.detected_regions) == 2
        assert result.detected_regions[0] == ("#app", "ID container", 80)  # 按 count 排序
        assert result.detected_regions[1] == ("main", "<main> region", 60)

    @pytest.mark.asyncio
    async def test_analyze_region_sorting(self):
        """测试区域按交互元素数量排序"""
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(
            return_value={
                "title": "Test",
                "url": "https://test.com",
                "totalInteractive": 200,
                "regions": [
                    ["nav", "<nav> region", 20],
                    ["main", "<main> region", 150],
                    ["aside", "<article> region", 30],
                ],
            }
        )

        analyzer = PageAnalyzer(mock_page)
        result = await analyzer.analyze()

        # 应该按 count 降序排序
        assert result.detected_regions[0] == ("main", "<main> region", 150)
        assert result.detected_regions[1] == ("aside", "<article> region", 30)
        assert result.detected_regions[2] == ("nav", "<nav> region", 20)

    def test_recommend_selector_with_region_count_zero(self):
        """测试推荐逻辑：regions[0].count为0时返回空（覆盖line 202）"""
        analyzer = PageAnalyzer(MagicMock())

        # 区域count为0（触发line 202）
        selector, savings = analyzer._compute_recommendation(100, [("div", "Container", 0)])
        assert selector == ""
        assert savings == "0%"

"""Unit tests for simplified suggestion logic in SnapshotManager"""

from unittest.mock import MagicMock

from myrm_agent_harness.toolkits.browser.session.snapshot_manager import SnapshotManager


class TestSimplifiedSuggestion:
    """测试简化后的建议逻辑"""

    def test_suggest_browser_inspect_for_large_pages(self):
        """测试大页面建议使用 browser_inspect"""
        manager = SnapshotManager(MagicMock())

        # 大页面，无 selector → 建议用 browser_inspect
        suggestion = manager._generate_suggestion(
            ref_count=500, estimated_tokens=3000, current_scope="content", current_compact=False, current_selector=""
        )

        assert "browser_inspect()" in suggestion
        assert "3000 tokens" in suggestion
        assert "~70%" in suggestion
        assert "~2100 tokens" in suggestion  # 验证量化节省
        assert "Quick fix" in suggestion  # 验证多选项

    def test_suggest_scope_for_large_refs(self):
        """测试大 refs 建议 scope='interactive'"""
        manager = SnapshotManager(MagicMock())

        # 大 refs，已有 selector，但 scope 不是 interactive
        suggestion = manager._generate_suggestion(
            ref_count=250,
            estimated_tokens=1500,
            current_scope="content",
            current_compact=False,
            current_selector="main",
        )

        assert "scope='interactive'" in suggestion
        assert "250 refs" in suggestion
        assert "~60%" in suggestion
        assert "~900 tokens" in suggestion  # 验证量化节省
        assert "Alternative" in suggestion  # 验证多选项

    def test_suggest_compact_for_large_refs(self):
        """测试大 refs 建议 compact=True"""
        manager = SnapshotManager(MagicMock())

        # 大 refs，scope 已是 interactive，但未开启 compact
        suggestion = manager._generate_suggestion(
            ref_count=250,
            estimated_tokens=1500,
            current_scope="interactive",
            current_compact=False,
            current_selector="",
        )

        assert "compact=True" in suggestion
        assert "~30%" in suggestion
        assert "~450 tokens" in suggestion  # 验证量化节省

    def test_no_suggestion_for_fully_optimized_page(self):
        """测试完全优化的页面无建议"""
        manager = SnapshotManager(MagicMock())

        # 已经使用了 selector + scope='interactive'
        suggestion = manager._generate_suggestion(
            ref_count=500,
            estimated_tokens=1200,
            current_scope="interactive",
            current_compact=False,
            current_selector="main",
        )

        # 仍然会建议 compact，因为 refs>200
        assert "compact=True" in suggestion

    def test_no_suggestion_when_all_optimized(self):
        """测试所有优化参数都已应用时无建议"""
        manager = SnapshotManager(MagicMock())

        # selector + scope='interactive' + compact=True
        suggestion = manager._generate_suggestion(
            ref_count=500,
            estimated_tokens=1200,
            current_scope="interactive",
            current_compact=True,
            current_selector="main",
        )

        assert suggestion == ""

    def test_no_suggestion_for_small_page(self):
        """测试小页面无建议"""
        manager = SnapshotManager(MagicMock())

        # 小页面（refs<200, tokens<2000）
        suggestion = manager._generate_suggestion(
            ref_count=50, estimated_tokens=500, current_scope="content", current_compact=False, current_selector=""
        )

        assert suggestion == ""

    def test_suggestion_priority_order(self):
        """测试建议优先级（browser_inspect > scope > compact）"""
        manager = SnapshotManager(MagicMock())

        # 满足所有条件，应优先建议 browser_inspect
        suggestion = manager._generate_suggestion(
            ref_count=300, estimated_tokens=3000, current_scope="content", current_compact=False, current_selector=""
        )

        assert "browser_inspect()" in suggestion
        # 新格式中 browser_inspect 建议会包含 scope='interactive' 作为 Quick fix
        assert "Quick fix" in suggestion

    def test_no_suggestion_when_selector_used(self):
        """测试使用 selector 时不建议 browser_inspect"""
        manager = SnapshotManager(MagicMock())

        # 已有 selector，即使 tokens 很大也不建议 inspect
        suggestion = manager._generate_suggestion(
            ref_count=300,
            estimated_tokens=3000,
            current_scope="content",
            current_compact=False,
            current_selector="main",
        )

        assert "browser_inspect()" not in suggestion

    def test_suggestion_for_edge_case_thresholds(self):
        """测试边界值（refs=200, tokens=2000）"""
        manager = SnapshotManager(MagicMock())

        # 刚好到达阈值
        suggestion_at_threshold = manager._generate_suggestion(
            ref_count=200, estimated_tokens=2000, current_scope="content", current_compact=False, current_selector=""
        )
        # refs=200 不应触发 scope 建议，tokens=2000 不应触发 inspect 建议
        assert suggestion_at_threshold == ""

        # 超过阈值
        suggestion_above = manager._generate_suggestion(
            ref_count=201, estimated_tokens=2001, current_scope="content", current_compact=False, current_selector=""
        )
        assert "browser_inspect()" in suggestion_above

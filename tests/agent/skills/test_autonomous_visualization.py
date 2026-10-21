"""
Tests for ZeroPromptAutonomousVisualizationAndDynamicWebDashboardEngine (Item 49 P1).
Validates intent detection heuristic accuracy and multi-table dynamic dashboard compilation.
Strictly under 220 lines. Zero Any.
"""

import pytest

from myrm_agent_harness.agent.skills.autonomous_visualization import (
    DataDashboardCompiler,
    VisualizationCategory,
    VisualizationIntentDetector,
)


class TestVisualizationIntentDetector:
    """Test suite for zero-prompt visualization intent recognition."""

    @pytest.fixture
    def detector(self) -> VisualizationIntentDetector:
        return VisualizationIntentDetector(min_confidence=0.5)

    def test_detect_trend_line_intent(self, detector: VisualizationIntentDetector) -> None:
        query = "请分析过去半年用户活跃度的历史走势与增长趋势"
        result = detector.detect(query)
        assert result.should_visualize is True
        assert result.category == VisualizationCategory.TREND_LINE
        assert result.confidence >= 0.5
        assert "trend:走势" in result.matched_signals
        assert result.suggested_renderer == "svg"

    def test_detect_comparison_bar_intent(self, detector: VisualizationIntentDetector) -> None:
        query = "对比三款开源大模型在基准测试中的综合性能排名与得分"
        result = detector.detect(query)
        assert result.should_visualize is True
        assert result.category == VisualizationCategory.COMPARISON_BAR
        assert result.confidence >= 0.5
        assert "comparison:对比" in result.matched_signals

    def test_detect_proportion_pie_intent(self, detector: VisualizationIntentDetector) -> None:
        query = "分析公司年度各部门研发费用的构成与预算占比分布"
        result = detector.detect(query)
        assert result.should_visualize is True
        assert result.category == VisualizationCategory.PROPORTION_PIE
        assert result.confidence >= 0.5

    def test_detect_funnel_intent(self, detector: VisualizationIntentDetector) -> None:
        query = "梳理注册到付费转化的核心链路，排查各环节的转化率与流失率"
        result = detector.detect(query)
        assert result.should_visualize is True
        assert result.category == VisualizationCategory.FUNNEL
        assert result.confidence >= 0.5

    def test_detect_topology_intent(self, detector: VisualizationIntentDetector) -> None:
        query = "请梳理认证服务与数据库之间的调用链与系统依赖关系拓扑"
        result = detector.detect(query)
        assert result.should_visualize is True
        assert result.category == VisualizationCategory.TOPOLOGY_GRAPH
        assert result.confidence >= 0.5

    def test_detect_data_dashboard_with_tabular_context(self, detector: VisualizationIntentDetector) -> None:
        query = "综合评估销售业务大盘经营数据概览"
        csv_context = """月份,销售额,订单数,转化率
2026-01,120000,450,12.5%
2026-02,135000,520,13.8%
2026-03,158000,610,15.2%
"""
        result = detector.detect(query, context_data=csv_context)
        assert result.should_visualize is True
        assert result.category == VisualizationCategory.DATA_DASHBOARD
        assert result.confidence >= 0.6
        assert "tabular_structure_detected" in result.matched_signals
        assert result.suggested_renderer == "interactive_html"

    def test_explicit_negative_rejection(self, detector: VisualizationIntentDetector) -> None:
        query = "对比一下方案A和方案B，但请纯文字输出，不要画图"
        result = detector.detect(query)
        assert result.should_visualize is False
        assert result.category == VisualizationCategory.NONE
        assert "explicit_text_only_requested" in result.matched_signals

    def test_unrelated_casual_query(self, detector: VisualizationIntentDetector) -> None:
        query = "今天天气不错，请写一首关于春天的短诗"
        result = detector.detect(query)
        assert result.should_visualize is False
        assert result.category == VisualizationCategory.NONE


class TestDataDashboardCompiler:
    """Test suite for DataDashboardCompiler spreadsheet compilation and HTML generation."""

    @pytest.fixture
    def compiler(self) -> DataDashboardCompiler:
        return DataDashboardCompiler()

    def test_compile_from_csv(self, compiler: DataDashboardCompiler) -> None:
        csv_data = """月份,总营收,新获客数,退款率
2026-01,100000,120,2.1
2026-02,125000,150,1.8
2026-03,160000,210,1.5
"""
        spec = compiler.compile_from_csv(csv_data, title="Q1 经营大盘")
        assert spec.title == "Q1 经营大盘"
        assert len(spec.kpis) >= 3
        # First KPI is total row count
        assert spec.kpis[0].label == "总数据行数"
        assert "3 条" in spec.kpis[0].value
        # Check numeric revenue KPI
        revenue_kpi = next((k for k in spec.kpis if k.label == "总营收"), None)
        assert revenue_kpi is not None
        assert revenue_kpi.trend == "up"

        # Check charts
        assert len(spec.charts) >= 1
        assert spec.charts[0].series[0].name == "总营收"
        assert len(spec.charts[0].series[0].data) == 3

        # Check table
        assert len(spec.tables) == 1
        assert spec.tables[0].headers == ["月份", "总营收", "新获客数", "退款率"]
        assert len(spec.tables[0].rows) == 3

    def test_compile_from_records(self, compiler: DataDashboardCompiler) -> None:
        records: list[dict[str, str | float | int]] = [
            {"region": "华东", "sales": 450000, "profit": 85000},
            {"region": "华南", "sales": 380000, "profit": 72000},
            {"region": "华北", "sales": 310000, "profit": 59000},
        ]
        spec = compiler.compile_from_records(records, title="区域销售概览")
        assert spec.title == "区域销售概览"
        assert len(spec.tables[0].rows) == 3
        assert any(k.label == "sales" for k in spec.kpis)

    def test_compile_to_standalone_html(self, compiler: DataDashboardCompiler) -> None:
        csv_data = """指标,数值
访问量,5000
点击量,1200
转化量,320
"""
        spec = compiler.compile_from_csv(csv_data, title="流量漏斗看板")
        html_output = compiler.compile_to_standalone_html(spec)

        assert "<!DOCTYPE html>" in html_output
        assert "<title>流量漏斗看板</title>" in html_output
        assert "kpi-card" in html_output
        assert "<svg" in html_output
        assert "<table>" in html_output
        assert "Myrm Agent Harness" in html_output

    def test_empty_csv_handling(self, compiler: DataDashboardCompiler) -> None:
        spec = compiler.compile_from_csv("", title="空数据看板")
        assert spec.title == "空数据看板"
        assert spec.kpis == []
        assert spec.charts == []
        assert spec.tables == []

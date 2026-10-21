"""
[INPUT]:
- myrm_agent_harness.observability.context_optimization::ContextOptimizationSavingsAuditor
- myrm_agent_harness.observability.context_optimization::EngineeringSignalAnalyzer
- myrm_agent_harness.observability.context_optimization::models

[OUTPUT]:
- Pytest unit tests verifying per-tool token savings audit, financial value calculation, 7-signal pattern detection, and role-based insight reports.

[POS]:
tests/observability/test_context_optimization.py — 上下文拦截节流审计器与工程信号分析单元测试。
"""

import pytest

from myrm_agent_harness.observability.context_optimization import (
    ContextOptimizationSavingsAuditor,
    EngineeringSignalAnalyzer,
    EngineeringSignalPattern,
    RoleEngineeringInsightReport,
    RoleInsightView,
)


def test_savings_auditor_single_tool_and_session_war_report() -> None:
    auditor = ContextOptimizationSavingsAuditor()

    # 1. 模拟 Playwright 网页抓取大输出：原始 400KB (100,000 tokens)，优化截断存根后 4KB (1,000 tokens)
    rec1 = auditor.record_tool_call(
        session_id="session-crawl-01",
        tool_name="playwright_scrape",
        original_bytes=400_000,
        optimized_bytes=4_000,
        cache_hit=False,
    )
    assert rec1.original_tokens == 100_000
    assert rec1.optimized_tokens == 1_000
    assert rec1.saved_tokens == 99_000
    assert rec1.savings_rate_pct == 99.0
    assert rec1.cost_saved_usd > 0.2
    assert rec1.cost_saved_cny > 1.5

    # 2. 模拟 Bash 执行长编译日志：原始 40,000 tokens，优化存根 2,000 tokens，缓存命中
    rec2 = auditor.record_tool_call(
        session_id="session-crawl-01",
        tool_name="bash_exec",
        original_bytes=160_000,
        optimized_bytes=8_000,
        cache_hit=True,
    )
    assert rec2.saved_tokens == 38_000
    assert rec2.cache_hit is True

    # 3. 获取单会话节流全景战报
    audit = auditor.get_session_audit("session-crawl-01")
    assert audit.session_id == "session-crawl-01"
    assert audit.total_tool_calls == 2
    assert audit.total_saved_tokens == 99_000 + 38_000  # 137,000
    assert audit.overall_savings_rate_pct > 95.0
    assert audit.total_cost_saved_usd > 0.4
    assert audit.total_cost_saved_cny > 2.8
    assert len(audit.tool_breakdown) == 2
    assert "🎉 本次会话通过智能上下文拦截为您节省了" in audit.summary_headline

    # 4. 空会话兜底
    empty_audit = auditor.get_session_audit("session-non-existent")
    assert empty_audit.total_tool_calls == 0
    assert empty_audit.total_saved_tokens == 0


def test_engineering_signal_analyzer_and_role_insights() -> None:
    auditor = ContextOptimizationSavingsAuditor()
    analyzer = EngineeringSignalAnalyzer(
        bloat_token_threshold=15_000,
        high_retry_threshold=3,
        blocking_io_ms_threshold=5_000.0,
    )

    # 记录 3 次工具调用
    r1 = auditor.record_tool_call(
        session_id="session-analysis-01",
        tool_name="file_cat_all",
        original_bytes=80_000,  # 20,000 tokens (超出 bloat 阈值 15,000)
        optimized_bytes=4_000,
        cache_hit=False,
    )
    r2 = auditor.record_tool_call(
        session_id="session-analysis-01",
        tool_name="api_http_get",
        original_bytes=8_000,
        optimized_bytes=2_000,
        cache_hit=False,
    )
    r3 = auditor.record_tool_call(
        session_id="session-analysis-01",
        tool_name="git_clone_repo",
        original_bytes=12_000,
        optimized_bytes=4_000,
        cache_hit=False,
    )

    audit = auditor.get_session_audit("session-analysis-01")

    # 模拟重试与阻塞指标
    retry_metrics = {"api_http_get": 4}  # 重试 4 次，超过 3
    latency_metrics = {"git_clone_repo": 6_500.0}  # 耗时 6.5s，超过 5s

    # 1. 扫描会话工程信号
    signals = analyzer.analyze_session_signals(
        audit=audit,
        tool_records=[r1, r2, r3],
        tool_retry_counts=retry_metrics,
        tool_latencies_ms=latency_metrics,
    )

    # 应检测出：TOOL_OUTPUT_BLOAT (file_cat_all), HIGH_RETRY_CHURN (api_http_get), LONG_BLOCKING_IO (git_clone_repo), CACHE_STARVATION (0% 命中)
    patterns = {s.signal_pattern for s in signals}
    assert EngineeringSignalPattern.TOOL_OUTPUT_BLOAT in patterns
    assert EngineeringSignalPattern.HIGH_RETRY_CHURN in patterns
    assert EngineeringSignalPattern.LONG_BLOCKING_IO in patterns
    assert EngineeringSignalPattern.CACHE_STARVATION in patterns

    # 2. 生成 CTO 角色视图洞察
    cto_report = analyzer.generate_role_insight(
        role=RoleInsightView.CTO,
        evaluated_sessions=[audit],
        all_signals=signals,
    )
    assert cto_report.role == RoleInsightView.CTO
    assert cto_report.total_saved_tokens_aggregate > 0
    assert "file_cat_all" in cto_report.top_efficiency_tools
    assert any(s.signal_pattern == EngineeringSignalPattern.TOOL_OUTPUT_BLOAT for s in cto_report.identified_engineering_signals)

    # 3. 生成 FinOps 角色视图洞察
    finops_report = analyzer.generate_role_insight(
        role=RoleInsightView.FINOPS,
        evaluated_sessions=[audit],
        all_signals=signals,
    )
    assert finops_report.role == RoleInsightView.FINOPS
    assert finops_report.total_cost_saved_usd_aggregate > 0
    assert any(s.signal_pattern == EngineeringSignalPattern.CACHE_STARVATION for s in finops_report.identified_engineering_signals)

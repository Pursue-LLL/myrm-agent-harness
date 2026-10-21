"""
Unit tests for Agentic Traffic Analytics, AEO Abandonment Diagnostics, and Funnel Telemetry.
Tests classification precision, sentinel page checks, and conversion aggregate reporting.
"""

from myrm_agent_harness.observability.agentic_traffic import (
    AbandonmentReason,
    AgentAbandonmentSentinel,
    AgentTrafficClassifier,
    AgentType,
    AgenticTrafficAnalyticsEngine,
    FunnelStage,
)


def test_agent_traffic_classifier_signatures() -> None:
    classifier = AgentTrafficClassifier()

    # 1. Cursor UA
    cursor_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Cursor/0.45.2 Chrome/120.0"
    agent_type, is_agent, conf = classifier.classify_request(cursor_ua)
    assert agent_type == AgentType.CURSOR
    assert is_agent is True
    assert conf >= 0.9

    # 2. Claude Code UA
    claude_ua = "claude-code/1.0.1 (darwin-arm64)"
    agent_type, is_agent, conf = classifier.classify_request(claude_ua)
    assert agent_type == AgentType.CLAUDE_CODE
    assert is_agent is True

    # 3. Custom Header overrides (e.g. Windsurf)
    custom_hdr = {"X-Agent-Client": "windsurf-agent/2.1"}
    agent_type, is_agent, conf = classifier.classify_request("Generic/1.0", headers=custom_hdr)
    assert agent_type == AgentType.WINDSURF
    assert is_agent is True

    # 4. Standard Human Chrome Browser
    human_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    headers = {"Sec-CH-UA": '"Chromium";v="128"'}
    agent_type, is_agent, conf = classifier.classify_request(human_ua, headers=headers, duration_ms=2500.0)
    assert agent_type == AgentType.HUMAN_BROWSER
    assert is_agent is False


def test_aeo_abandonment_sentinel_heuristics() -> None:
    sentinel = AgentAbandonmentSentinel()

    # 1. 优秀 AEO 页面（代码前置、llms.txt 支持）
    good_content = """# Myrm SDK Quickstart
Refer to `/llms.txt` for full API map.
```python
import myrm
client = myrm.Client()
```
Here is the rest of the documentation.
"""
    diag_good = sentinel.diagnose_page(
        path="/docs/quickstart",
        content=good_content,
        has_llms_txt_declared=True,
    )
    assert diag_good.aeo_score >= 80
    assert AbandonmentReason.NONE in diag_good.abandonment_reasons
    assert diag_good.has_code_in_first_500_tokens is True

    # 2. 超长页面 (> 20k tokens)
    huge_content = "Word " * 90000  # 450,000 chars -> ~112,500 tokens
    diag_huge = sentinel.diagnose_page(path="/docs/huge-spec", content=huge_content)
    assert AbandonmentReason.TOKEN_OVERFLOW_20K in diag_huge.abandonment_reasons
    assert diag_huge.aeo_score <= 70

    # 3. 前 500 Token 缺乏核心代码且缺失 llms.txt
    vague_content = "This is a very long introductory essay about AI history without any code." * 100
    diag_vague = sentinel.diagnose_page(path="/docs/intro", content=vague_content)
    assert AbandonmentReason.LLMS_TXT_MISSING in diag_vague.abandonment_reasons
    assert AbandonmentReason.FIRST_500_TOKENS_VAGUE in diag_vague.abandonment_reasons

    # 4. 纯 SPA 空白客户端渲染
    blank_spa = '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
    diag_spa = sentinel.diagnose_page(path="/dashboard", content=blank_spa)
    assert AbandonmentReason.SPA_CLIENT_BLANK in diag_spa.abandonment_reasons


def test_agentic_traffic_analytics_engine_and_funnel_summary() -> None:
    engine = AgenticTrafficAnalyticsEngine()

    # 记录 1: Cursor 访问优秀文档
    good_md = "# Quickstart\n```python\nimport myrm\n```\nSee llms.txt"
    r1 = engine.record_visit(
        visit_id="v-01",
        user_agent="Cursor/0.45",
        target_path="/docs/quickstart",
        duration_ms=450.0,
        page_content=good_md,
        has_llms_txt_declared=True,
    )
    assert r1.is_agent is True
    assert r1.agent_type == AgentType.CURSOR
    assert r1.funnel_stage == FunnelStage.CONTEXT_ABSORBED

    # 记录 2: Claude Code 发起沙箱与 API 试调
    r2 = engine.record_visit(
        visit_id="v-02",
        user_agent="claude-code/1.0",
        target_path="/api/v1/sandbox/probe",
        duration_ms=1200.0,
        status_code=200,
    )
    assert r2.is_agent is True
    assert r2.funnel_stage == FunnelStage.SANDBOX_PROBED

    # 记录 3: 普通人类浏览器
    r3 = engine.record_visit(
        visit_id="v-03",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128.0",
        target_path="/pricing",
        headers={"Sec-CH-UA": '"Chromium";v="128"'},
        duration_ms=4500.0,
    )
    assert r3.is_agent is False
    assert r3.agent_type == AgentType.HUMAN_BROWSER

    # 获取全景报表
    summary = engine.get_summary()
    assert summary.total_visits == 3
    assert summary.agent_visits_count == 2
    assert summary.human_visits_count == 1
    assert summary.agent_traffic_ratio_pct == 66.67
    assert summary.top_agents["CURSOR"] == 1
    assert summary.top_agents["CLAUDE_CODE"] == 1
    assert summary.funnel_conversion[FunnelStage.CONTEXT_ABSORBED.value] == 1
    assert summary.funnel_conversion[FunnelStage.SANDBOX_PROBED.value] == 1

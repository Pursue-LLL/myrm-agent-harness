"""
[INPUT]:
- myrm_agent_harness.observability.context_breakdown::ContextBreakdownResolver, ContextAlertLevel

[OUTPUT]:
- Pytest verification for real tag parsing (memory, workspace, skills, tool results), 60%/90% alert thresholds, and dual telemetry.

[POS]:
tests/observability/test_context_breakdown.py — 上下文用量七分类精准解析与警戒线单元测试。
"""

import pytest

from myrm_agent_harness.observability.context_breakdown import (
    ContextAlertLevel,
    ContextBreakdownResolver,
)


def test_context_breakdown_real_injection_tag_parsing() -> None:
    resolver = ContextBreakdownResolver()

    system_content = (
        "You are an expert software engineer assistant.\n"
        "<user_memory_context>\n"
        "User prefers Python 3.13 and strict PEP8 guidelines. Never use Any type.\n"
        "</user_memory_context>\n"
        "<workspace_context>\n"
        "Active Workspace: /workspace/project. Rules: maintain documentation integrity.\n"
        "</workspace_context>\n"
        "<sandbox_environment_snapshot>\n"
        "OS: mac, Node: 20, Python: 3.13\n"
        "</sandbox_environment_snapshot>\n"
    )

    messages = [
        {
            "role": "user",
            "content": (
                "<bound_skills>\n"
                "- web-search: Web retrieval capability\n"
                "- code-review: Static analysis SOP\n"
                "</bound_skills>\n"
                "Please help me analyze the performance bottleneck."
            ),
        },
        {
            "role": "assistant",
            "content": "Let me inspect the code using the terminal.",
        },
        {
            "role": "tool",
            "content": "profiling output: CPU 98% in hot loop function line 42",
        },
    ]

    snapshot = resolver.resolve(
        system_content=system_content,
        messages=messages,
        tools_schema_tokens=250,
        provider_actual_tokens=1200,
        total_window_tokens=10000,
    )

    categories = snapshot.categories
    # 验证真实注入标签全部被分离识别并计量（不再丢失进 other 或被截断为 0）
    assert categories["system_prompt"].estimated_tokens > 0
    assert categories["memory"].estimated_tokens > 0
    assert categories["workspace"].estimated_tokens > 0
    assert categories["skills"].estimated_tokens > 0
    assert categories["tools_schema"].estimated_tokens == 250
    assert categories["tool_results"].estimated_tokens > 0
    assert categories["chat_messages"].estimated_tokens > 0

    # 验证估算总和与提供商上报并列
    assert snapshot.provider_actual_tokens == 1200
    assert snapshot.estimated_sum_tokens > 0


def test_context_breakdown_alert_levels_60_and_90() -> None:
    resolver = ContextBreakdownResolver()
    window = 10000

    # 1. 正常用量：30% < 60%
    snap_normal = resolver.resolve(
        system_content="You are a helpful assistant.",
        provider_actual_tokens=3000,
        total_window_tokens=window,
    )
    assert snap_normal.alert_level == ContextAlertLevel.NORMAL
    assert snap_normal.usage_ratio_pct == 30.0

    # 2. 60% 性能衰减警戒线：65% (>= 60% and < 90%)
    snap_warn = resolver.resolve(
        system_content="You are a helpful assistant.",
        provider_actual_tokens=6500,
        total_window_tokens=window,
    )
    assert snap_warn.alert_level == ContextAlertLevel.WARNING_60
    assert snap_warn.usage_ratio_pct == 65.0
    assert "60%" in snap_warn.alert_message

    # 3. 90% 深度压缩临界线：92% (>= 90%)
    snap_crit = resolver.resolve(
        system_content="You are a helpful assistant.",
        provider_actual_tokens=9200,
        total_window_tokens=window,
    )
    assert snap_crit.alert_level == ContextAlertLevel.CRITICAL_90
    assert snap_crit.usage_ratio_pct == 92.0
    assert "自动深度压缩" in snap_crit.alert_message

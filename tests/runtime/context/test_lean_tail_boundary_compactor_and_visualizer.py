"""Unit tests for Lean-Tail Boundary Compactor and Context Lifecycle Visualizer.

Verifies strict protect_first_n and protect_last_n preservation on 50-turn
conversations, anchor harvesting from middle history, three-tier audit reporting,
and dashboard/UI payload generation for frontend visualizers.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.context_lifecycle_visualizer import (
    ContextLifecycleVisualizer,
)
from myrm_agent_harness.runtime.context.context_lifecycle_visualizer_types import (
    ContextSectionKind,
    LeanTailBoundaryConfig,
)
from myrm_agent_harness.runtime.context.lean_tail_boundary_compactor import (
    LeanTailBoundaryCompactor,
)


def _generate_50_turn_conversation() -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    # 1. First 3 messages: System and core persona / rules
    messages.append({
        "role": "system",
        "content": "你是一名资深全栈工程师，负责 Myrm Agent 核心架构构建。",
    })
    messages.append({
        "role": "user",
        "content": "初始规则要求：单文件不超过 400 行，严禁使用 Any 类型，严格保真。",
    })
    messages.append({
        "role": "assistant",
        "content": "收到，严格遵循 0 Any、单文件 <400 行与保护性提交工作流。",
    })

    # 2. Middle 27 messages (turns 4 to 30): Iterative exploration and agreements
    for i in range(4, 31):
        if i == 10:
            content = "【关键决定】：约定数据库连接池最大连接数限制为 50，超时为 30s。"
        elif i == 18:
            content = "【重要目标】：确认采用基于 Token 预算的渐进式尾部保护策略。"
        elif i == 25:
            content = "【待办配置】：完成 Dockerfile 多阶段构建与健康检查探针配置。"
        else:
            content = f"中间执行细节 {i}：辅助代码分析与模块测试调试过程数据记录。"
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": content})

    # 3. Last 20 messages (turns 31 to 50): Active execution and latest tool outputs
    for j in range(31, 51):
        role = "user" if j % 2 == 1 else "assistant"
        content = f"活跃执行轮次 {j}：正在运行自动化集成测试套件并校验返回值。"
        messages.append({"role": role, "content": content})

    return messages


def test_50_turn_conversation_strict_head_and_tail_preservation() -> None:
    """Verifies verbatim head (first 3) and tail (last 20) protection during compaction."""
    messages = _generate_50_turn_conversation()
    assert len(messages) == 50

    compactor = LeanTailBoundaryCompactor(
        config=LeanTailBoundaryConfig(
            protect_first_n=3,
            protect_last_n=20,
            trigger_threshold_ratio=0.01,  # Force compaction for test
        )
    )

    assembled, report = compactor.compact(
        messages=messages,
        session_id="sess_50_turns",
        context_window_size=10_000,
    )

    assert report.session_id == "sess_50_turns"
    assert report.needs_compaction is True
    assert report.total_messages_before == 50
    # Expected: 3 head + 1 summary + 20 tail = 24 messages
    assert len(assembled) == 24
    assert report.total_messages_after == 24

    # 1. Assert Head (first 3) is 100% verbatim
    for idx in range(3):
        assert assembled[idx]["role"] == messages[idx]["role"]
        assert assembled[idx]["content"] == messages[idx]["content"]

    # 2. Assert Middle message is compacted history summary
    summary_msg = assembled[3]
    assert summary_msg["role"] == "user"
    assert "<compacted_middle_history>" in summary_msg["content"]
    assert "约定数据库连接池" in summary_msg["content"]
    assert "渐进式尾部保护" in summary_msg["content"]

    # 3. Assert Tail (last 20) is 100% verbatim
    for offset in range(1, 21):
        assert assembled[-offset]["role"] == messages[-offset]["role"]
        assert assembled[-offset]["content"] == messages[-offset]["content"]

    # 4. Assert Key anchors extracted
    assert len(report.retained_anchors) >= 3
    assert any("数据库连接池" in a for a in report.retained_anchors)
    assert any("渐进式尾部保护" in a for a in report.retained_anchors)
    assert report.tokens_saved > 0
    assert report.compression_ratio < 1.0


def test_visualizer_ascii_dashboard_and_ui_payload() -> None:
    """Verifies that the visualizer formats structured payload and dashboard correctly."""
    messages = _generate_50_turn_conversation()
    compactor = LeanTailBoundaryCompactor(
        config=LeanTailBoundaryConfig(
            protect_first_n=3,
            protect_last_n=20,
            trigger_threshold_ratio=0.01,
        )
    )
    _, report = compactor.compact(
        messages=messages,
        session_id="sess_vis_test",
        context_window_size=10_000,
    )

    # 1. Test UI JSON payload
    ui_payload = ContextLifecycleVisualizer.build_ui_payload(report)
    assert ui_payload["session_id"] == "sess_vis_test"
    assert ui_payload["total_messages_before"] == 50
    assert ui_payload["total_messages_after"] == 24
    assert ui_payload["tokens_saved"] > 0
    assert ui_payload["savings_percentage"] > 0.0
    assert len(ui_payload["sections"]) == 3

    head_sec = ui_payload["sections"][0]
    mid_sec = ui_payload["sections"][1]
    tail_sec = ui_payload["sections"][2]

    assert head_sec["kind"] == ContextSectionKind.HEAD_PROTECTED.value
    assert head_sec["is_compressed"] is False
    assert head_sec["message_count"] == 3

    assert mid_sec["kind"] == ContextSectionKind.MIDDLE_COMPACTED.value
    assert mid_sec["is_compressed"] is True
    assert mid_sec["message_count"] == 27

    assert tail_sec["kind"] == ContextSectionKind.TAIL_PROTECTED.value
    assert tail_sec["is_compressed"] is False
    assert tail_sec["message_count"] == 20

    # 2. Test ASCII Dashboard text rendering
    dashboard_text = ContextLifecycleVisualizer.render_ascii_dashboard(report)
    assert "上下文生命周期与三段式瘦身看板" in dashboard_text
    assert "HEAD_PROTECTED: 3 条消息" in dashboard_text
    assert "MIDDLE_COMPACTED: 27 条消息" in dashboard_text
    assert "TAIL_PROTECTED: 20 条消息" in dashboard_text
    assert "关键约定与待办保留项" in dashboard_text


def test_short_conversation_within_budget_skips_compaction() -> None:
    """Verifies that conversation within budget is kept untouched without compaction."""
    short_messages = [
        {"role": "system", "content": "系统设定"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，请问有什么可以帮助您的？"},
    ]

    compactor = LeanTailBoundaryCompactor()
    assembled, report = compactor.compact(
        messages=short_messages,
        session_id="sess_short",
        context_window_size=128_000,
    )

    assert report.needs_compaction is False
    assert report.tokens_saved == 0
    assert report.compression_ratio == 1.0
    assert len(assembled) == len(short_messages)
    assert assembled == short_messages

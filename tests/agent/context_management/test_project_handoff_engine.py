"""Unit tests for Ten-Second Cross-Session Project Handoff Protocol Suite (Item 218).

[INPUT]
- TenSecondProjectHandoffEngine, ProjectHandoffConfig, ProjectHandoffStatus.
- Simulated mock workspace avatar files and re-prompting queries.

[OUTPUT]
- Deterministic verification of re-prompt intent detection, workspace dossier sniffing,
- and instant 10-second alignment handshake generation.

[POS]
- Verifies zero-context cold start handoff without repeating project background.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.project_handoff import (
    HandoffHandshakeResponse,
    ProjectHandoffConfig,
    ProjectHandoffStatus,
    ProjectWorkspaceDossier,
    TenSecondProjectHandoffEngine,
)


def test_reprompt_intent_detection() -> None:
    """Verifies recognition of user handoff prompts requesting zero background re-explanation."""
    engine = TenSecondProjectHandoffEngine()

    assert engine.is_reprompt_handoff_intent("请接手当前项目，不要让我重复讲背景。") is True
    assert engine.is_reprompt_handoff_intent("先读取项目规则和当前状态文件，告诉我接下来该做什么") is True
    assert engine.is_reprompt_handoff_intent("请接手项目，继续推进") is True
    assert engine.is_reprompt_handoff_intent("resume project from overview") is True

    # Standard query should NOT trigger handoff intent
    assert engine.is_reprompt_handoff_intent("帮我写一个快速排序算法") is False
    assert engine.is_reprompt_handoff_intent("今天天气怎么样？") is False


def test_workspace_avatar_sniffing_and_parsing() -> None:
    """Verifies file sniffing from workspace mock data extracting rules, milestones, and blockers."""
    engine = TenSecondProjectHandoffEngine()

    mock_files = {
        "AGENTS.md": """
        # 项目员工手册
        - 原则: 所有模块必须配备单元测试，覆盖率 > 90%
        - 必须: 架构保持 0 Any，严格强类型
        - 严禁: 严禁向后兼容糟糕设计
        """,
        "00_项目总览.md": """
        # 00_项目总览.md（流动工作看板）
        ## 【当前阶段目标】
        第 2 阶段 · 支付网关对接与结算状态机落地
        ## 【已拍板事实与确认标准】
        - 采用 Stripe API v2026
        ## 【现有成果清单】
        - 04_交付成果/payment_types.py
        - 04_交付成果/stripe_adapter.py
        - 04_交付成果/webhook_handler.py
        ## 【当前卡点与待决策事项】
        - 等待财务审核退款时效 SLA
        ## 【下一步具体交付动作】
        编写 Webhook 幂等重放测试用例
        """,
    }

    dossier = engine.sniff_workspace_dossier(workspace_root="/mock/workspace", files_map=mock_files)

    assert dossier.rules_file_found is True
    assert dossier.status_file_found is True
    assert dossier.rule_principles_count >= 3
    assert "第 2 阶段 · 支付网关对接" in dossier.current_goal
    assert dossier.deliverables_count == 3
    assert len(dossier.pending_blockers) == 1
    assert "财务审核退款时效" in dossier.pending_blockers[0]
    assert "编写 Webhook 幂等重放测试用例" in dossier.suggested_next_action


def test_handshake_response_generation() -> None:
    """Verifies generation of structured, zero-fluff 10-second alignment handshake response."""
    engine = TenSecondProjectHandoffEngine()

    mock_files = {
        "AGENTS.md": "- 原则: 严禁向后兼容\n- 必须: 提交前运行全量回归",
        "00_项目总览.md": """
        ## 【当前阶段目标】
        完成核心引擎开发
        ## 【现有成果清单】
        - 模块 A
        - 模块 B
        ## 【当前卡点与待决策事项】
        无阻碍，进行中
        ## 【下一步具体交付动作】
        开始编写集成测试
        """,
    }

    dossier = engine.sniff_workspace_dossier(workspace_root="/mock/workspace", files_map=mock_files)
    response = engine.generate_handshake_response(dossier)

    assert response.status == ProjectHandoffStatus.HANDSHAKE_COMPLETED
    assert response.ready_for_execution is True
    assert response.generation_duration_ms >= 0.0

    md = response.handshake_markdown
    assert "🤝 **项目分身已就绪，当前工作现场已对齐**：" in md
    assert "- 🎯 **当前阶段**：完成核心引擎开发" in md
    assert "- 📑 **核心规则与约束**：`AGENTS.md`" in md
    assert "- ✅ **已确认成果**：已沉淀 2 项阶段性产物" in md
    assert "- ⚠️ **当前待决策事项**：无阻塞，各项前置准备均已就绪" in md
    assert "- 🚀 **下一步建议动作**：开始编写集成测试" in md
    assert "已为您建立轻量冷启动上下文" in md


def test_handshake_response_when_no_avatar_present() -> None:
    """Verifies graceful fallback response when workspace has no project avatar files."""
    engine = TenSecondProjectHandoffEngine()
    empty_dossier = engine.sniff_workspace_dossier(workspace_root="/empty/dir", files_map={})

    response = engine.generate_handshake_response(empty_dossier)
    assert response.status == ProjectHandoffStatus.NO_AVATAR_DETECTED
    assert response.ready_for_execution is False
    assert "未在当前工作区检测到项目分身文件" in response.handshake_markdown

"""Unit tests for Static Rule AGENTS.md and Dynamic Status Overview Suite (Item 217).

[INPUT]
- DualFileProjectContextDecouplingEngine, DualFileDecouplingConfig.
- Simulated AGENTS.md rule text and 00_项目总览.md operational dashboard content.

[OUTPUT]
- Deterministic verification of static rule parsing, 5-section status extraction,
- markdown rendering, incremental status reflection, and dual-channel prompt envelopes.

[POS]
- Verifies physical decoupling of permanent principles from fast-evolving milestones.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.dual_file_decoupling import (
    DualFileDecouplingConfig,
    DualFileProjectContextDecouplingEngine,
    DynamicOverviewSections,
)


def test_static_rules_parsing_and_invariants() -> None:
    """Verifies that permanent project rules are parsed with principle and forbidden constraints."""
    engine = DualFileProjectContextDecouplingEngine()
    sample_agents_md = """
    # AGENTS.md - 项目员工手册与长期稳定规矩

    - 原则: 所有工位严格保持职责单一，禁止越界修改系统配置。
    - 红线: 01_原件目录绝对只读，严禁直接覆盖原始凭证文件。
    - 必须: 重大改动或破坏性指令必须先向用户请求明确确认。
    - 严禁: 严禁向后兼容糟糕设计，消除一切无用代码与 Any 类型。
    """

    spec = engine.parse_static_rules(sample_agents_md, source_path="AGENTS.md")
    assert spec.rule_source_path == "AGENTS.md"
    assert len(spec.sha256_hash) == 64
    assert len(spec.forbidden_actions) >= 2
    assert any("01_原件目录" in f for f in spec.forbidden_actions)
    assert any("Any 类型" in f for f in spec.forbidden_actions)
    assert len(spec.core_principles) >= 2
    assert any("向用户请求明确确认" in p for p in spec.core_principles)


def test_dynamic_overview_five_section_parsing_and_rendering() -> None:
    """Verifies parsing of standard 5-section markdown dashboard and deterministic re-rendering."""
    engine = DualFileProjectContextDecouplingEngine()
    sample_overview_md = """
    # 00_项目总览.md（流动工作看板）

    ## 【当前阶段目标】
    完成电商订单服务重构并交付 SQLite 仓储层基底

    ## 【已拍板事实与确认标准】
    - 采用纯净 Type Hints，全链路禁止使用 Any
    - 接口遵循 RESTful 规范，状态机采用枚举定义

    ## 【现有成果清单】
    - 04_交付成果/order_models.py (数据模型)
    - 04_交付成果/order_repo.py (仓储实现)

    ## 【当前卡点与待决策事项】
    - 等待支付网关 Webhook 签名公钥配置确认

    ## 【下一步具体交付动作】
    - 编写集成测试用例并验证状态转移
    """

    sections = engine.parse_dynamic_overview(sample_overview_md)
    assert "完成电商订单服务重构" in sections.current_phase_goal
    assert len(sections.established_facts) == 2
    assert "采用纯净 Type Hints" in sections.established_facts[0]
    assert len(sections.deliverables) == 2
    assert "order_models.py" in sections.deliverables[0]
    assert len(sections.blockers_and_decisions) == 1
    assert "支付网关 Webhook" in sections.blockers_and_decisions[0]
    assert len(sections.next_actions) == 1
    assert "编写集成测试用例" in sections.next_actions[0]

    # Deterministic round-trip rendering
    rendered_md = engine.render_dynamic_overview_markdown(sections)
    assert "## 【当前阶段目标】" in rendered_md
    assert "## 【已拍板事实与确认标准】" in rendered_md
    assert "## 【现有成果清单】" in rendered_md
    assert "## 【当前卡点与待决策事项】" in rendered_md
    assert "## 【下一步具体交付动作】" in rendered_md
    assert "order_models.py" in rendered_md


def test_incremental_status_reflection() -> None:
    """Verifies incremental updates to active overview sections upon task completion."""
    engine = DualFileProjectContextDecouplingEngine()
    initial_sections = DynamicOverviewSections(
        current_phase_goal="Phase 1: 数据层",
        established_facts=["事实 A"],
        deliverables=["成果 A"],
        blockers_and_decisions=["卡点 1"],
        next_actions=["行动 1"],
    )

    updated = engine.reflect_status_update(
        current_sections=initial_sections,
        new_goal="Phase 2: 服务层",
        added_facts=["事实 B"],
        added_deliverables=["成果 B"],
        updated_blockers=[],
        next_actions=["行动 2", "行动 3"],
    )

    assert updated.current_phase_goal == "Phase 2: 服务层"
    assert updated.established_facts == ["事实 A", "事实 B"]
    assert updated.deliverables == ["成果 A", "成果 B"]
    assert updated.blockers_and_decisions == []
    assert updated.next_actions == ["行动 2", "行动 3"]


def test_dual_file_envelope_assembly() -> None:
    """Verifies construction of decoupled dual-channel context envelopes for agent prompts."""
    engine = DualFileProjectContextDecouplingEngine()
    rules_text = "Invariant: Safety first. Never delete system files."
    status_text = "## 【当前阶段目标】\nSprint 42 final sprint."

    envelope = engine.build_dual_file_envelope(rules_text, status_text)
    assert "[PROJECT STATIC INVARIANT RULES: AGENTS.md]" in envelope.system_invariant_frame
    assert "Invariant: Safety first." in envelope.system_invariant_frame
    assert "[PROJECT ACTIVE STATUS DASHBOARD: 00_项目总览.md]" in envelope.dynamic_status_frame
    assert "Sprint 42" in envelope.dynamic_status_frame
    assert len(envelope.rule_hash) == 64
    assert len(envelope.status_hash) == 64
    assert envelope.cached_invariant_tokens_estimate > 0
    assert envelope.active_status_tokens_estimate > 0

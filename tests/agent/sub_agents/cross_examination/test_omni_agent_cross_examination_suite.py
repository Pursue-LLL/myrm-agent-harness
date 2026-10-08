# [INPUT]: AdoptionChoice, AgentRoleTarget, ConsensusDeltaHighlighter, IntentCategory, OmniAgentUnifiedDispatcherAndSplitCrossExaminationSuite, OneClickArbitrator, SplitCrossExaminationEngine, UnifiedIntentDispatcher
# [OUTPUT]: test_omni_agent_cross_examination_suite.py
# [POS]: tests/agent/sub_agents/cross_examination/test_omni_agent_cross_examination_suite.py

"""Unit test suite for OmniAgentUnifiedDispatcherAndSplitCrossExaminationSuite (Item 314).

Verifies:
1. Unified intent dispatcher classifying high-risk security, architectural trade-offs, research, and coding intents.
2. Consensus and delta highlighter extracting key claims, agreement score, polar divergences, and rendering dashboard.
3. Split cross-examination engine orchestrating multi-agent evaluations with custom or default perspectives.
4. One-click arbitrator resolving lead agent, specific agent, and synthesized consensus with context injection block.
5. End-to-end facade coordinating single-entry dispatch, cross-examination, dashboard display, and adoption.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.cross_examination import (
    AdoptionChoice,
    AgentExecutionOutput,
    AgentRoleTarget,
    ConsensusDeltaHighlighter,
    CrossExamArbitrationReport,
    IntentCategory,
    OmniAgentDispatcherSuite,
    OmniAgentUnifiedDispatcherAndSplitCrossExaminationSuite,
    OneClickArbitrator,
    SplitCrossExaminationEngine,
    UnifiedIntentDispatcher,
)


def test_unified_intent_dispatcher_routing_and_cross_exam_candidacy() -> None:
    dispatcher = UnifiedIntentDispatcher()

    # 1. High-risk security inquiry
    sec_dec = dispatcher.route_intent("rm -rf /var/lib/data 并在生产数据库清空所有表")
    assert sec_dec.primary_agent == AgentRoleTarget.SECURITY_CRITIC
    assert sec_dec.category == IntentCategory.SECURITY_HIGH_RISK
    assert sec_dec.is_cross_exam_candidate is True
    assert AgentRoleTarget.SECURITY_CRITIC in sec_dec.suggested_cross_exam_agents
    assert sec_dec.confidence >= 0.9

    # 2. Architectural trade-off inquiry
    arch_dec = dispatcher.route_intent("Redis vs Memcached 方案对比与架构选型权衡分析")
    assert arch_dec.primary_agent == AgentRoleTarget.ARCHITECT_PLANNER
    assert arch_dec.category == IntentCategory.ARCHITECTURAL_DECISION
    assert arch_dec.is_cross_exam_candidate is True
    assert len(arch_dec.suggested_cross_exam_agents) >= 2

    # 3. Deep research inquiry
    res_dec = dispatcher.route_intent("调研业界前沿 Agent 记忆系统的最新进展与行业综述报告")
    assert res_dec.primary_agent == AgentRoleTarget.DEEP_RESEARCH
    assert res_dec.category == IntentCategory.RESEARCH_SURVEY

    # 4. Coding implementation inquiry
    code_dec = dispatcher.route_intent("重构代码并编写 pytest 单元测试，修复类型报错")
    assert code_dec.primary_agent == AgentRoleTarget.CODING_SPECIALIST
    assert code_dec.category == IntentCategory.DEVELOPMENT_ENGINEERING

    # 5. Routine quick command
    quick_dec = dispatcher.route_intent("git status")
    assert quick_dec.primary_agent == AgentRoleTarget.LOCAL_FAST
    assert quick_dec.is_cross_exam_candidate is False


def test_consensus_delta_highlighter_claims_consensus_and_divergence() -> None:
    highlighter = ConsensusDeltaHighlighter()

    out_sec = AgentExecutionOutput(
        agent_role=AgentRoleTarget.SECURITY_CRITIC,
        display_name="Security Critic",
        content="Deploying strict authentication tokens is necessary. We must restrict permissions to prevent unauthorized execution. Require manual sign-off.",
        latency_ms=25.0,
        key_claims=(
            "Deploying strict authentication tokens is necessary",
            "We must restrict permissions to prevent unauthorized execution",
            "Require manual sign-off",
        ),
    )

    out_code = AgentExecutionOutput(
        agent_role=AgentRoleTarget.CODING_SPECIALIST,
        display_name="Coding Specialist",
        content="Deploying strict authentication tokens is necessary. Optimize execution throughput by pipelining async calls. Avoid redundant checks.",
        latency_ms=18.0,
        key_claims=(
            "Deploying strict authentication tokens is necessary",
            "Optimize execution throughput by pipelining async calls",
        ),
    )

    consensus = highlighter.compute_consensus((out_sec, out_code))
    assert len(consensus.common_ground_facts) >= 1
    assert "authentication" in consensus.common_ground_facts[0].lower()
    assert 0.0 <= consensus.agreement_score <= 1.0

    divergences = highlighter.detect_divergences((out_sec, out_code))
    assert len(divergences) >= 1
    assert any("Velocity vs Blast-Radius" in d.topic for d in divergences)


def test_split_cross_examination_engine_custom_and_default_executors() -> None:
    engine = SplitCrossExaminationEngine()

    query = "如何安全重构分布式缓存失效策略？"
    roles = (
        AgentRoleTarget.SECURITY_CRITIC,
        AgentRoleTarget.ARCHITECT_PLANNER,
        AgentRoleTarget.CODING_SPECIALIST,
    )

    # Custom executors for 2 roles, 1 fallback to default
    custom_map = {
        AgentRoleTarget.CODING_SPECIALIST: lambda q: f"Custom Code Perspective for '{q}'. Implement write-through caching.",
        AgentRoleTarget.ARCHITECT_PLANNER: lambda q: f"Custom Architect Perspective for '{q}'. Decouple cache invalidation event bus.",
    }

    report = engine.conduct_cross_examination(
        query=query,
        target_roles=roles,
        custom_executors=custom_map,
    )

    assert report.query == query
    assert len(report.agent_outputs) == 3
    assert report.recommended_lead_agent in roles
    assert len(report.synthesized_recommendation) > 20


def test_one_click_arbitrator_adoption_modes() -> None:
    arbitrator = OneClickArbitrator()
    engine = SplitCrossExaminationEngine()

    report = engine.conduct_cross_examination(
        query="数据库迁移回滚方案评估",
        target_roles=(AgentRoleTarget.SECURITY_CRITIC, AgentRoleTarget.ARCHITECT_PLANNER),
    )

    # 1. Adopt Synthesized Consensus
    synth_receipt = arbitrator.adopt_verdict(
        report=report,
        choice=AdoptionChoice.SYNTHESIZED_CONSENSUS,
    )
    assert synth_receipt.choice == AdoptionChoice.SYNTHESIZED_CONSENSUS
    assert "Adopted Multi-Agent Consensus" in synth_receipt.context_injection_block
    assert synth_receipt.adopted_agent == report.recommended_lead_agent

    # 2. Adopt Specific Agent (e.g., SECURITY_CRITIC)
    sec_receipt = arbitrator.adopt_verdict(
        report=report,
        choice=AdoptionChoice.SPECIFIC_AGENT,
        specific_agent_role=AgentRoleTarget.SECURITY_CRITIC,
    )
    assert sec_receipt.choice == AdoptionChoice.SPECIFIC_AGENT
    assert sec_receipt.adopted_agent == AgentRoleTarget.SECURITY_CRITIC
    assert "Security Review" in sec_receipt.context_injection_block


def test_omni_agent_suite_end_to_end_facade() -> None:
    suite = OmniAgentUnifiedDispatcherAndSplitCrossExaminationSuite()

    query = "PostgreSQL vs MongoDB 技术选型与数据安全审计"

    # Step 1: Dispatch query
    decision = suite.dispatch_query(query)
    assert decision.is_cross_exam_candidate is True
    assert len(decision.suggested_cross_exam_agents) >= 2

    # Step 2: Run Split Cross-Examination
    report = suite.run_cross_examination(query)
    assert len(report.agent_outputs) >= 2

    # Step 3: Render Dashboard
    dashboard_md = suite.render_dashboard(report)
    assert "Multi-Agent Split Cross-Examination" in dashboard_md
    assert "Common Ground" in dashboard_md
    assert "Participant Agent Outputs" in dashboard_md

    # Step 4: Adopt verdict
    receipt = suite.adopt_verdict(
        report=report,
        choice=AdoptionChoice.SYNTHESIZED_CONSENSUS,
    )
    assert "Adopted Multi-Agent Consensus" in receipt.context_injection_block
    assert receipt.adopted_summary != ""

    # Verify alias
    assert OmniAgentDispatcherSuite is OmniAgentUnifiedDispatcherAndSplitCrossExaminationSuite

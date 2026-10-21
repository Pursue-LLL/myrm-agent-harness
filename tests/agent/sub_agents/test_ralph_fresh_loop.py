"""
[INPUT]
- pytest
- myrm_agent_harness.agent.sub_agents.ralph_loop (RalphHandoffReport, RalphLoopConfig, RalphFreshAgentLoopCoordinator, sanitize_handoff_report, evaluate_blocked_guardrail, compose_fresh_agent_directive)

[OUTPUT]
- test_handoff_capacity_sanitization: 测试五字段容量硬顶清洗
- test_min_three_round_blocked_guardrail: 测试尝试满三轮阻断防御与降级
- test_fresh_agent_prompt_composition: 测试无历史 Fresh 子 Agent 根提示词装配
- test_coordinator_lifecycle_and_transition: 测试 Coordinator 多轮生命周期与状态流转

[POS]
Harness 框架层 Ralph 式 Fresh-Agent 多轮循环自动化测试套件（Topic 12 · 第 15 项）。
覆盖容量硬顶、Min-3-Round 阻断拦截、Fresh 提示词装配与轮次状态流转。
"""


from myrm_agent_harness.agent.sub_agents.ralph_loop import (
    RalphFreshAgentLoopCoordinator,
    RalphHandoffReport,
    RalphLoopConfig,
    compose_fresh_agent_directive,
    evaluate_blocked_guardrail,
    sanitize_handoff_report,
)


def test_handoff_capacity_sanitization() -> None:
    """验证五字段交接报告在容量超限时进行安全截断。"""
    config = RalphLoopConfig(max_handoff_chars=500)

    # 构造超长交接
    giant_text = "A" * 600
    report = RalphHandoffReport(
        status="in_progress",
        summary=giant_text,
        evidence="tests/output.log",
        next_steps="Continue optimization",
        blocker="",
    )
    assert report.total_chars() > 500

    sanitized = sanitize_handoff_report(report, config)
    assert "...[truncated]" in sanitized.summary
    assert sanitized.total_chars() <= 600


def test_min_three_round_blocked_guardrail() -> None:
    """验证尝试满三轮阻断防御规则 (Min-3-Round Rule)。"""
    config = RalphLoopConfig(min_rounds_before_blocked=3)

    report = RalphHandoffReport(
        status="blocked",
        summary="Hit compilation issue",
        evidence="error.log: missing symbol",
        next_steps="Need assistance",
        blocker="Compiler flag mismatch",
    )

    # 第 1 轮声称 blocked：触发降级
    d_report1, was_downgraded1 = evaluate_blocked_guardrail(report, round_index=1, config=config)
    assert was_downgraded1 is True
    assert d_report1.status == "in_progress"
    assert "[Ralph Guardrail]" in d_report1.next_steps

    # 第 2 轮声称 blocked：依然触发降级
    d_report2, was_downgraded2 = evaluate_blocked_guardrail(report, round_index=2, config=config)
    assert was_downgraded2 is True
    assert d_report2.status == "in_progress"

    # 第 3 轮声称 blocked：满 3 轮门槛，合规接受
    d_report3, was_downgraded3 = evaluate_blocked_guardrail(report, round_index=3, config=config)
    assert was_downgraded3 is False
    assert d_report3.status == "blocked"


def test_fresh_agent_prompt_composition() -> None:
    """验证为新一轮 Fresh 子 Agent 装配满血零历史指令。"""
    prior_handoff = RalphHandoffReport(
        status="in_progress",
        summary="Set up database schema and migration scripts",
        evidence="db/schema.sql, tests/test_db.py",
        next_steps="Implement CRUD queries and indexing",
        blocker="",
    )

    prompt = compose_fresh_agent_directive(
        human_goal="Build resilient distributed metadata service",
        workspace_root="/sandbox/workspace",
        round_index=2,
        max_rounds=5,
        prior_handoff=prior_handoff,
    )

    assert "Round: 2 / 5" in prompt
    assert "Context Status: FRESH (无前置对话历史，满血全新推理)" in prompt
    assert "Shared Workspace: /sandbox/workspace" in prompt
    assert "Build resilient distributed metadata service" in prompt
    assert "Set up database schema and migration scripts" in prompt
    assert "Implement CRUD queries and indexing" in prompt


def test_coordinator_lifecycle_and_transition() -> None:
    """验证 Coordinator 全生命周期推进与状态流转。"""
    coordinator = RalphFreshAgentLoopCoordinator()

    # 1. 创建会话
    session = coordinator.create_session(
        human_goal="Refactor authentication layer",
        workspace_root="/work/repo",
        config=RalphLoopConfig(max_rounds=4, min_rounds_before_blocked=3),
    )
    assert session.current_round == 1
    assert session.status == "in_progress"

    # 2. 生成 Round 1 初始指令 (无前置交接)
    prompt_r1 = coordinator.generate_next_round_directive(session.session_id)
    assert "Round: 1 / 4" in prompt_r1
    assert "Prior Round Handoff" not in prompt_r1

    # 3. 提交 Round 1 (尝试声称 blocked，验证被拦截降级)
    r1_handoff = RalphHandoffReport(
        status="blocked",
        summary="Token validation failed",
        evidence="logs/auth.err",
        next_steps="Ask human",
        blocker="JWT secret missing",
    )
    rec1 = coordinator.record_round_completion(
        session_id=session.session_id,
        child_session_id="child-sess-01",
        raw_handoff=r1_handoff,
        duration_seconds=12.5,
        tokens_consumed=4200,
    )
    assert rec1.was_blocked_downgraded is True
    assert rec1.handoff.status == "in_progress"
    assert session.status == "in_progress"
    assert session.current_round == 2

    # 4. 生成 Round 2 指令 (带上一轮交接信息)
    prompt_r2 = coordinator.generate_next_round_directive(session.session_id)
    assert "Round: 2 / 4" in prompt_r2
    assert "Prior Round Handoff (Structured 5-Field)" in prompt_r2

    # 5. 提交 Round 2 (正常 in_progress)
    r2_handoff = RalphHandoffReport(
        status="in_progress",
        summary="Fixed JWT secret generation fallback",
        evidence="auth/jwt.py:45",
        next_steps="Run integration suite",
        blocker="",
    )
    rec2 = coordinator.record_round_completion(
        session_id=session.session_id,
        child_session_id="child-sess-02",
        raw_handoff=r2_handoff,
        duration_seconds=8.0,
        tokens_consumed=3100,
    )
    assert rec2.was_blocked_downgraded is False
    assert session.current_round == 3

    # 6. 提交 Round 3 (完成任务)
    r3_handoff = RalphHandoffReport(
        status="completed",
        summary="All authentication tests pass with 100% coverage",
        evidence="pytest report: 18/18 passed",
        next_steps="Ready for deployment",
        blocker="",
    )
    rec3 = coordinator.record_round_completion(
        session_id=session.session_id,
        child_session_id="child-sess-03",
        raw_handoff=r3_handoff,
        duration_seconds=5.2,
        tokens_consumed=2500,
    )
    assert rec3.handoff.status == "completed"
    assert session.status == "completed"
    assert len(session.rounds) == 3

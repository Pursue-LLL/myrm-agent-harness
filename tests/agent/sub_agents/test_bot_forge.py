"""Unit tests for Chat-Driven Agent & Team Factory with Builder Safety Envelope."""

import pytest

from myrm_agent_harness.agent.sub_agents.bot_forge import (
    BotProfileSpec,
    BuilderAuthority,
    BuilderSafetyEnvelope,
    BuilderSafetyViolationError,
    OverlapVerdictEnum,
    PipelineStageEnum,
    TeamCompositionSpec,
    VerifiedCreationPipeline,
)


@pytest.fixture
def base_builder() -> BuilderAuthority:
    return BuilderAuthority(
        builder_name="lead-architect",
        allowed_tools=["bash_exec", "file_read", "file_write", "web_search", "git_status"],
        allowed_skills=["code_review", "data_analysis", "ast_lint"],
        allowed_mcps=["github", "sqlite"],
        can_create_agents=True,
        max_team_members=4,
    )


def test_safety_envelope_anti_recursion(base_builder: BuilderAuthority) -> None:
    """Ensure child bot cannot be granted meta-creation tools (prevents recursive self-replication)."""
    bad_spec = BotProfileSpec(
        name="meta-clone",
        display_name="Meta Cloner",
        description="Creates other bots recursively",
        system_prompt="You build more agents",
        tools=["file_read", "bot_forge"],
    )

    with pytest.raises(BuilderSafetyViolationError, match="Recursive creation denied"):
        BuilderSafetyEnvelope.validate_profile_safety(base_builder, bad_spec)


def test_safety_envelope_permission_attenuation(base_builder: BuilderAuthority) -> None:
    """Ensure child bot cannot exceed the builder's own permission authority."""
    escalated_spec = BotProfileSpec(
        name="super-bot",
        display_name="Super Bot",
        description="Bot with ungranted admin privileges",
        system_prompt="Do everything",
        tools=["file_read", "delete_production_database"],
    )

    with pytest.raises(BuilderSafetyViolationError, match="Permission escalation"):
        BuilderSafetyEnvelope.validate_profile_safety(base_builder, escalated_spec)


def test_name_and_duty_overlap_detection() -> None:
    """Test duplicate naming and semantic keyword overlap detection."""
    existing = [
        BotProfileSpec(
            name="sec-auditor",
            display_name="Security Auditor",
            description="Performs cryptographic audits, token governance, and vulnerability analysis",
            system_prompt="Audit systems",
        )
    ]

    # Duplicate name check
    v1, conflict1, rec1 = BuilderSafetyEnvelope.detect_name_and_duty_overlap(
        candidate_name="sec-auditor",
        candidate_purpose="New auditor",
        existing_agents=existing,
    )
    assert v1 == OverlapVerdictEnum.DUPLICATE_NAME
    assert conflict1 == "sec-auditor"
    assert "sec-auditor-specialist" in str(rec1)

    # Duty overlap check
    v2, conflict2, rec2 = BuilderSafetyEnvelope.detect_name_and_duty_overlap(
        candidate_name="crypto-checker",
        candidate_purpose="Performs cryptographic audits, token governance, and vulnerability analysis",
        existing_agents=existing,
    )
    assert v2 == OverlapVerdictEnum.OVERLAPPING_DUTY
    assert conflict2 == "sec-auditor"
    assert "significantly overlaps" in str(rec2)


def test_clone_prompt_sanitization() -> None:
    """Ensure old bot display name occurrences are sanitized to the new identity."""
    old_prompt = "You are Alice. Alice specializes in API design. If anyone asks, Alice knows best."
    sanitized = BuilderSafetyEnvelope.sanitize_clone_prompt(
        original_name="Alice",
        new_name="bob-designer",
        system_prompt=old_prompt,
    )
    assert "Alice" not in sanitized
    assert "You are bob-designer." in sanitized
    assert "bob-designer specializes in API design." in sanitized


def test_single_agent_creation_success(base_builder: BuilderAuthority) -> None:
    """Execute end-to-end single agent creation through all stages to COMPLETED."""
    agent_store = {}
    cron_store = {}
    pipeline = VerifiedCreationPipeline(
        builder=base_builder,
        agent_store=agent_store,
        cron_store=cron_store,
    )

    spec = BotProfileSpec(
        name="daily-reporter",
        display_name="Daily Reporter",
        description="Compiles daily financial transaction reports and metrics",
        system_prompt="Generate executive summaries",
        model="gpt-5",
        tools=["file_read", "web_search"],
        cron_routines=["0 9 * * 1-5"],
    )

    state = pipeline.create_single_agent(spec)
    assert state.current_stage == PipelineStageEnum.COMPLETED
    assert "daily-reporter" in state.created_agents
    assert "daily-reporter" in agent_store
    assert len(cron_store) == 1
    assert state.verification is not None
    assert state.verification.passed is True


def test_precheck_unready_model_failure_with_rollback(base_builder: BuilderAuthority) -> None:
    """Ensure requesting an unconfigured model aborts immediately with zero store mutations."""
    agent_store = {}
    cron_store = {}
    pipeline = VerifiedCreationPipeline(
        builder=base_builder,
        available_models={"gpt-5", "claude-3-7-sonnet"},
        agent_store=agent_store,
        cron_store=cron_store,
    )

    spec = BotProfileSpec(
        name="quantum-bot",
        display_name="Quantum Bot",
        description="Quantum computation solver",
        system_prompt="Solve quantum equations",
        model="unconfigured-quantum-model-v99",
        tools=["file_read"],
    )

    state = pipeline.create_single_agent(spec)
    assert state.current_stage == PipelineStageEnum.ROLLED_BACK
    assert "is not configured or ready" in str(state.error)
    assert len(agent_store) == 0
    assert len(cron_store) == 0


def test_team_atomic_creation_and_atomic_rollback(base_builder: BuilderAuthority) -> None:
    """If one member of a team fails, ALL members must be rolled back atomically."""
    agent_store = {}
    cron_store = {}
    pipeline = VerifiedCreationPipeline(
        builder=base_builder,
        available_tools={"file_read", "file_write", "bash_exec"},
        agent_store=agent_store,
        cron_store=cron_store,
    )

    team_spec = TeamCompositionSpec(
        team_name="fullstack-duo",
        team_purpose="Full stack web engineering squad",
        lead=BotProfileSpec(
            name="lead-coder",
            display_name="Lead Coder",
            description="Coordinates feature tickets and reviews pull requests",
            system_prompt="Coordinate codebase",
            tools=["file_read", "file_write"],
        ),
        specialists=[
            BotProfileSpec(
                name="frontend-bot",
                display_name="Frontend Bot",
                description="Implements React components",
                system_prompt="Code UI",
                tools=["file_read", "file_write"],
            ),
            # This member requests web_search, which is allowed by builder but missing from available_tools
            BotProfileSpec(
                name="backend-bot",
                display_name="Backend Bot",
                description="Database optimizer",
                system_prompt="Optimize queries",
                tools=["file_read", "web_search"],
            ),
        ],
    )

    state = pipeline.create_team(team_spec)
    assert state.current_stage == PipelineStageEnum.ROLLED_BACK
    assert "failed creation" in str(state.error)

    # Verify atomic rollback: neither lead-coder nor frontend-bot remain in store!
    assert "lead-coder" not in agent_store
    assert "frontend-bot" not in agent_store
    assert "backend-bot" not in agent_store
    assert len(agent_store) == 0
    assert state.rollback is not None
    assert "lead-coder" in state.rollback.reverted_agents

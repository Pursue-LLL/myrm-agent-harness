"""Unit tests for Orchestrator Squad Composition, Model-Deferred Wizard, and Budget Allocator (Item 34).

[INPUT]
- myrm_agent_harness.agent.coordination.squad_composition::{
    SquadBlueprintComposer,
    SquadBudgetAllocator,
    SquadRoleTier,
    ModelDeferredChoice,
  }

[OUTPUT]
- Pytest cases validating automatic role synthesis, SOUL prompt composition,
  compute budget partitioning, fan-out safety gates, and Phase-2 Model-Deferred materialization.

[POS]
- myrm-agent-harness/tests/agent/coordination/test_squad_composition.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.coordination.squad_composition import (
    ModelDeferredChoice,
    SquadBlueprintComposer,
    SquadBudgetAllocator,
    SquadRoleTier,
)


def test_compose_blueprint_standard_trinity() -> None:
    goal = "Build a modern dashboard application"
    blueprint = SquadBlueprintComposer.compose_blueprint(
        goal_description=goal,
        total_budget_tokens=120000,
        total_max_cost_usd=1.80,
    )

    assert blueprint.squad_id.startswith("squad_")
    assert blueprint.goal_description == goal
    assert len(blueprint.members) == 3

    roles = {m.role_tier for m in blueprint.members}
    assert roles == {
        SquadRoleTier.ORCHESTRATOR,
        SquadRoleTier.CODER,
        SquadRoleTier.REVIEWER,
    }

    # Verify SOUL prompt generation
    orchestrator = next(m for m in blueprint.members if m.role_tier == SquadRoleTier.ORCHESTRATOR)
    assert "# SOUL Profile: Squad Conductor" in orchestrator.soul_system_prompt
    assert "Never implement deep code yourself" in orchestrator.soul_system_prompt
    assert orchestrator.suggested_model_tier == "reasoning"

    coder = next(m for m in blueprint.members if m.role_tier == SquadRoleTier.CODER)
    assert "Strictly obey PEP8, zero Any types" in coder.soul_system_prompt

    # Verify budget summation
    allocated_tokens = sum(m.budget_tokens for m in blueprint.members)
    assert allocated_tokens == 120000

    allocated_usd = round(sum(m.max_cost_usd for m in blueprint.members), 2)
    assert allocated_usd == 1.80


def test_compose_blueprint_with_researcher() -> None:
    goal = "Investigate the codebase authentication flow, refactor token handling, and verify security"
    blueprint = SquadBlueprintComposer.compose_blueprint(
        goal_description=goal,
        total_budget_tokens=200000,
        total_max_cost_usd=2.50,
    )

    assert len(blueprint.members) == 4
    role_keys = {m.role_key for m in blueprint.members}
    assert role_keys == {"orchestrator", "researcher", "coder", "reviewer"}

    researcher = next(m for m in blueprint.members if m.role_key == "researcher")
    assert researcher.handle == "@scout"
    assert "Produce concise, evidence-driven summaries" in researcher.soul_system_prompt
    assert researcher.suggested_model_tier == "fast"


def test_budget_allocator_math_and_bounds() -> None:
    goal = "Refactor database migrations and optimize slow queries"
    blueprint = SquadBlueprintComposer.compose_blueprint(
        goal_description=goal,
        total_budget_tokens=100000,
        total_max_cost_usd=1.50,
    )

    for m in blueprint.members:
        assert m.budget_tokens >= 1000
        assert m.max_cost_usd > 0
        assert m.stop_condition.max_turns >= 5
        assert m.stop_condition.max_tool_calls >= 10

    # Negative/Zero input guards
    with pytest.raises(ValueError, match="positive"):
        SquadBudgetAllocator.allocate_budget(blueprint.members, 0, 1.0)

    with pytest.raises(ValueError, match="positive"):
        SquadBudgetAllocator.allocate_budget(blueprint.members, 50000, -0.5)


def test_squad_safety_invariants() -> None:
    # Empty goal test
    with pytest.raises(ValueError, match="cannot be empty"):
        SquadBlueprintComposer.compose_blueprint("   ")

    # Empty members test
    is_safe, msg = SquadBudgetAllocator.validate_squad_safety(())
    assert not is_safe
    assert "cannot be empty" in msg

    # Max descendants limit
    bp = SquadBlueprintComposer.compose_blueprint("Quick test suite")
    is_safe, msg = SquadBudgetAllocator.validate_squad_safety(bp.members, max_descendants_per_run=2)
    assert not is_safe
    assert "exceeds max descendants" in msg


def test_model_deferred_materialization() -> None:
    goal = "Deploy multi-tenant Redis cache layer"
    blueprint = SquadBlueprintComposer.compose_blueprint(
        goal_description=goal,
        total_budget_tokens=150000,
        total_max_cost_usd=2.00,
    )

    # Phase 2: User provides Model-Deferred choices
    choices = {
        "orchestrator": ModelDeferredChoice(
            role_key="orchestrator",
            selected_model_id="gpt-4o",
            custom_instructions="Focus on latency minimization.",
        ),
        "coder": ModelDeferredChoice(
            role_key="coder",
            selected_model_id="claude-3-5-sonnet",
        ),
        "reviewer": ModelDeferredChoice(
            role_key="reviewer",
            selected_model_id="gemini-1.5-pro",
        ),
    }

    materialized = SquadBlueprintComposer.materialize_squad(
        blueprint=blueprint,
        model_choices=choices,
    )

    assert materialized.squad_id == blueprint.squad_id
    assert materialized.status == "active"
    assert materialized.orchestrator_bot_id.startswith("bot_orchestrator_")
    assert len(materialized.members) == len(blueprint.members)

    mat_orch = next(m for m in materialized.members if m.role_key == "orchestrator")
    assert mat_orch.selected_model_id == "gpt-4o"
    assert "Focus on latency minimization." in mat_orch.system_prompt
    assert mat_orch.allocated_budget_tokens == blueprint.members[0].budget_tokens

    mat_coder = next(m for m in materialized.members if m.role_key == "coder")
    assert mat_coder.selected_model_id == "claude-3-5-sonnet"

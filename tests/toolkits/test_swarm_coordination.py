"""Unit tests for SwarmCoordinationEngine.

[INPUT]
- myrm_agent_harness.toolkits.swarm: SwarmCoordinationEngine, SwarmSubagentTask, RecalledRuleItem, OwnerRiskItem

[OUTPUT]
- Pytest test cases verifying swarm configuration, recalled rules prompt compilation, and owner risk confirmations.

[POS]
Harness framework layer tests for Item 42 P0.
Strictly under 120 lines. Zero `Any`.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.swarm import (
    OwnerRiskItem,
    RecalledRuleItem,
    SwarmCoordinationEngine,
    SwarmSubagentTask,
)


def test_swarm_mode_config() -> None:
    engine = SwarmCoordinationEngine()
    session_id = "sess_swarm_01"

    # Default disabled
    cfg = engine.get_config(session_id)
    assert cfg.enabled is False
    assert cfg.concurrency_quota == 5

    # Update config with boundary check
    updated = engine.set_config(session_id, enabled=True, concurrency_quota=15)
    assert updated.enabled is True
    assert updated.concurrency_quota == 10  # Clamped to max 10


def test_subagent_task_assignment() -> None:
    engine = SwarmCoordinationEngine()
    session_id = "sess_swarm_tasks"

    tasks = [
        SwarmSubagentTask(
            task_id="t_01",
            role_title="Inventory Analyst",
            boundary_description="Analyze raw material and supply chain costs",
            assigned_tools=["sql_query", "excel_calc"],
        ),
        SwarmSubagentTask(
            task_id="t_02",
            role_title="Compliance Reviewer",
            boundary_description="Verify food hygiene license and municipal regulations",
        ),
    ]

    assigned = engine.assign_tasks(session_id, tasks)
    assert len(assigned) == 2
    assert engine.get_tasks(session_id)[0].role_title == "Inventory Analyst"


def test_recalled_rules_management_and_prompt_compilation() -> None:
    engine = SwarmCoordinationEngine()
    session_id = "sess_rules_01"

    rules = [
        RecalledRuleItem(
            rule_id="rule_01",
            summary="Vegan menu options must comprise at least 30% of total offerings",
            source_turn_id="turn_04",
            confidence=0.96,
            category="menu_constraint",
        ),
        RecalledRuleItem(
            rule_id="rule_02",
            summary="Operating hours restricted to 09:00 - 22:00 due to residential zone",
            source_turn_id="turn_02",
            confidence=0.88,
            category="operating_hours",
        ),
    ]

    engine.record_recalled_rules(session_id, rules)
    prompt = engine.compile_active_rules_prompt(session_id)
    assert "[@active_rules: Verified Memory & Business Guidelines]" in prompt
    assert "Vegan menu options" in prompt
    assert "Operating hours restricted" in prompt

    # Toggle one rule inactive
    toggled = engine.toggle_rule_active(session_id, "rule_02", is_active=False)
    assert toggled is not None
    assert toggled.is_active is False

    # Check compiled prompt excludes inactive rule
    updated_prompt = engine.compile_active_rules_prompt(session_id)
    assert "Vegan menu options" in updated_prompt
    assert "Operating hours restricted" not in updated_prompt


def test_owner_risk_items_and_confirmation() -> None:
    engine = SwarmCoordinationEngine()
    session_id = "sess_risks_01"

    risks = [
        OwnerRiskItem(
            risk_id="risk_01",
            title="Commercial Kitchen Power Load",
            description="High-voltage steam oven may exceed tenant electric capacity limit (40kW)",
            severity="high",
            external_constraint_type="property_utility",
            remediation_hint="Verify substation capacity with building property manager",
        ),
    ]

    engine.register_risks(session_id, risks)
    listed = engine.get_risks(session_id)
    assert len(listed) == 1
    assert listed[0].is_confirmed is False

    # Owner confirms risk item
    confirmed = engine.set_risk_confirmation(
        session_id, "risk_01", is_confirmed=True, confirmed_by="store_manager_zhang"
    )
    assert confirmed is not None
    assert confirmed.is_confirmed is True
    assert confirmed.confirmed_by == "store_manager_zhang"

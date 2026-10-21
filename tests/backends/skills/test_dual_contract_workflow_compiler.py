"""Architecture guard: House Conventions vs Hard Invariants dual contract.

[INPUT]
- myrm_agent_harness.backends.skills.workflow_compiler.WorkflowIntentPlan
- myrm_agent_harness.backends.skills.workflow_compiler.WorkflowSkillCompiler

[OUTPUT]
- Tests verifying:
  1. WorkflowIntentPlan properly captures hard_invariants and house_conventions.
  2. Compiler emits the dual-contract rule hierarchy sections.
  3. Anti-arguing graceful yielding instructions are embedded in house conventions.
"""

from __future__ import annotations

from myrm_agent_harness.backends.skills.workflow_compiler import (
    WorkflowIntentPlan,
    WorkflowPlanStep,
    WorkflowSkillCompiler,
)


def test_workflow_compiler_dual_contract_compilation() -> None:
    plan = WorkflowIntentPlan(
        name="contract-governed-skill",
        description="A skill governed by hard invariants and house conventions",
        intent="Enforce security invariants while respecting user style overrides",
        steps=[
            WorkflowPlanStep(
                step_id="step-1",
                title="Generate Deliverable",
                description="Produce output according to client guidelines",
            )
        ],
        hard_invariants=[
            "Never exfiltrate credentials or PII outside the sandbox boundary.",
            "Never execute drop database or rm -rf without user confirmation.",
        ],
        house_conventions=[
            "Prefer concise bullet points with maximum 6 items per slide.",
            "Use camelCase for internal variable identifiers.",
        ],
    )

    markdown = WorkflowSkillCompiler.compile(plan)

    # Assert Rule Hierarchy
    assert "## Rule Hierarchy & Compliance" in markdown
    assert "### Hard Invariants (Unbreakable Rules)" in markdown
    assert "- **[Hard Invariant]**: Never exfiltrate credentials" in markdown
    assert "### House Conventions (Team Defaults & Style Preferences)" in markdown
    assert "gracefully yield without arguing or lecturing" in markdown
    assert "- **[House Convention]**: Prefer concise bullet points" in markdown


def test_workflow_intent_plan_serialization_roundtrip() -> None:
    plan = WorkflowIntentPlan(
        name="roundtrip-skill",
        description="test serialization",
        intent="test intent",
        steps=[],
        hard_invariants=["No unauthorized writes"],
        house_conventions=["Default to dark mode"],
    )

    data = plan.to_dict()
    assert data["hard_invariants"] == ["No unauthorized writes"]
    assert data["house_conventions"] == ["Default to dark mode"]

    restored = WorkflowIntentPlan.from_dict(data)
    assert restored.hard_invariants == ["No unauthorized writes"]
    assert restored.house_conventions == ["Default to dark mode"]

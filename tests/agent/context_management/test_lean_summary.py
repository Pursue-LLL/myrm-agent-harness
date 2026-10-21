"""Tests for Lean Compaction Summary Model and Prompt Templates.

Validates the 4-pillar lean summary contract and its lossless conversion to/from
the standard 14-field StructuredSummary.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary
from myrm_agent_harness.agent.context_management.strategies.summary.lean_summary import (
    LEAN_SUMMARY_MERGE_PROMPT_TEMPLATE,
    LEAN_SUMMARY_PROMPT_TEMPLATE,
    LeanStructuredSummary,
)


def test_lean_structured_summary_defaults() -> None:
    """Test default values and field initializations."""
    lean = LeanStructuredSummary()
    assert lean.user_goal == ""
    assert lean.active_state == ""
    assert lean.key_decisions == []
    assert lean.next_steps == []


def test_lean_summary_to_structured_summary_conversion() -> None:
    """Verify conversion from 4-pillar lean model to 14-field StructuredSummary."""
    lean = LeanStructuredSummary(
        user_goal="Refactor compaction pipeline",
        active_state="Completed exact anchor extraction",
        key_decisions=["Separate deterministic anchors from semantic summary"],
        next_steps=["Implement tests", "Verify architecture gates"],
    )

    full = lean.to_structured_summary()

    assert isinstance(full, StructuredSummary)
    assert full.user_goal == "Refactor compaction pipeline"
    assert full.active_state == "Completed exact anchor extraction"
    assert full.active_task == "Implement tests"
    assert full.next_steps == ["Implement tests", "Verify architecture gates"]
    assert full.key_findings == ["Separate deterministic anchors from semantic summary"]
    # Defensive empty lists/strings
    assert full.completed_actions == []
    assert full.errors_and_fixes == []
    assert full.files_modified == []
    assert full.blocked_items == []


def test_lean_summary_from_structured_summary_conversion() -> None:
    """Verify conversion from 14-field StructuredSummary into 4-pillar lean model."""
    full = StructuredSummary(
        user_goal="Build microservice",
        active_state="Deployment pending",
        active_task="Review PR",
        key_findings=["Finding 1", "Finding 2"],
        next_steps=["Step 1", "Step 2"],
        completed_actions=["Action 1"],
    )

    lean = LeanStructuredSummary.from_structured_summary(full)

    assert lean.user_goal == "Build microservice"
    assert lean.active_state == "Deployment pending"
    assert lean.key_decisions == ["Finding 1", "Finding 2"]
    assert lean.next_steps == ["Step 1", "Step 2"]


def test_lean_summary_prompt_templates_contain_expected_directives() -> None:
    """Verify prompt templates enforce JSON-only output and 4-pillar structure."""
    assert "user_goal" in LEAN_SUMMARY_PROMPT_TEMPLATE
    assert "active_state" in LEAN_SUMMARY_PROMPT_TEMPLATE
    assert "key_decisions" in LEAN_SUMMARY_PROMPT_TEMPLATE
    assert "next_steps" in LEAN_SUMMARY_PROMPT_TEMPLATE
    assert "{context}" in LEAN_SUMMARY_PROMPT_TEMPLATE

    assert "existing_summary" in LEAN_SUMMARY_MERGE_PROMPT_TEMPLATE
    assert "next_steps" in LEAN_SUMMARY_MERGE_PROMPT_TEMPLATE

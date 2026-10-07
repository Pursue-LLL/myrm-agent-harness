"""Unit tests for ArchitectureIntentConvergenceGate."""

import pytest

from myrm_agent_harness.agent.context_management.architecture_gate import (
    ArchitectureIntentConvergenceGate,
    ArchitectureMode,
    ExecutionBlueprintStep,
    TechnologyOption,
)


def test_adaptive_discussion_mode_trigger_and_destructive_tool_suppression() -> None:
    """Verify high-risk prompts trigger advisory mode and suppress destructive tools."""
    gate = ArchitectureIntentConvergenceGate()
    session_id = "sess-arch-001"

    prompt = "我们要重构前端富文本编辑器模块，需要评估选型与整体架构"
    triggered = gate.evaluate_requirement(session_id, prompt)

    assert triggered is True
    assert gate.get_mode(session_id) == ArchitectureMode.DISCUSSION_ADVISORY

    # Destructive write tools must be strictly suppressed
    allowed, reason = gate.is_tool_allowed(session_id, "write_file")
    assert allowed is False
    assert "架构研讨与意图收敛门禁态" in reason

    allowed_replace, _ = gate.is_tool_allowed(session_id, "replace_file_content")
    assert allowed_replace is False

    # Readonly tools must be allowed
    allowed_read, _ = gate.is_tool_allowed(session_id, "read_file")
    assert allowed_read is True


def test_multi_option_tradeoff_matrix_registration() -> None:
    """Verify multi-option trade-off matrix registration and rationale tracking."""
    gate = ArchitectureIntentConvergenceGate()
    session_id = "sess-arch-002"

    options = [
        TechnologyOption(
            option_id="opt-tiptap",
            name="TipTap (ProseMirror)",
            summary="Headless wrapper over ProseMirror with active ecosystem.",
            pros=("Rich extensions", "Collaborative editing ready (Y.js)"),
            cons=("Slightly higher bundle size",),
            complexity_score=5,
            performance_score=9,
            is_recommended=True,
        ),
        TechnologyOption(
            option_id="opt-lexical",
            name="Lexical (Meta)",
            summary="Lightweight, modern editor framework from Meta.",
            pros=("Extreme performance", "Clean React bindings"),
            cons=("Steeper learning curve", "Smaller plugin ecosystem"),
            complexity_score=8,
            performance_score=10,
            is_recommended=False,
        ),
    ]

    matrix = gate.create_tradeoff_matrix(
        session_id=session_id,
        problem_statement="Choose editor engine for collaborative document editing.",
        options=options,
        recommended_id="opt-tiptap",
        rationale="TipTap provides out-of-the-box CRDT/Y.js bindings and extensive community plugins.",
    )

    assert matrix.recommended_option_id == "opt-tiptap"
    assert len(matrix.options) == 2
    assert gate.get_mode(session_id) == ArchitectureMode.DISCUSSION_ADVISORY

    eval_result = gate.get_evaluation_result(session_id)
    assert eval_result.active_matrix is not None
    assert eval_result.active_matrix.matrix_id == matrix.matrix_id
    assert eval_result.destructive_tools_suppressed is True


def test_blueprint_generation_and_convergence_card_rendering() -> None:
    """Verify blueprint generation advances to INTENT_CONVERGING and renders structured XML card."""
    gate = ArchitectureIntentConvergenceGate()
    session_id = "sess-arch-003"

    # Setup matrix
    gate.create_tradeoff_matrix(
        session_id=session_id,
        problem_statement="Editor stack selection.",
        options=[
            TechnologyOption(
                option_id="opt-1",
                name="TipTap",
                summary="Editor framework",
                pros=("Active",),
                cons=(),
                complexity_score=4,
                performance_score=8,
                is_recommended=True,
            )
        ],
        recommended_id="opt-1",
        rationale="Best balance.",
    )

    # Generate blueprint
    steps = [
        ExecutionBlueprintStep(
            step_id="step-1",
            order=1,
            title="Install @tiptap dependencies",
            description="Add packages and configure tailwind typography plugin.",
            acceptance_criteria=("Dependencies resolved in package.json",),
            affected_components=("package.json", "tailwind.config.js"),
        ),
        ExecutionBlueprintStep(
            step_id="step-2",
            order=2,
            title="Implement Core Editor Component",
            description="Create RichTextEditor.tsx with toolbar and extensions.",
            acceptance_criteria=("Component mounts without errors",),
            affected_components=("src/components/editor/RichTextEditor.tsx",),
        ),
    ]

    blueprint = gate.generate_execution_blueprint(
        session_id=session_id,
        selected_option_id="opt-1",
        title="Collaborative TipTap Editor Rollout",
        steps=steps,
    )

    assert blueprint.is_approved_by_user is False
    assert gate.get_mode(session_id) == ArchitectureMode.INTENT_CONVERGING

    # Render interactive card
    card_xml = gate.render_interactive_convergence_card(session_id)
    assert "<intent_convergence_card>" in card_xml
    assert "mode='INTENT_CONVERGING'" in card_xml
    assert "Collaborative TipTap Editor Rollout" in card_xml
    assert "Install @tiptap dependencies" in card_xml


def test_user_approval_and_execution_unlock() -> None:
    """Verify explicit user approval switches mode to EXECUTION_LOCKED and unlocks write tools."""
    gate = ArchitectureIntentConvergenceGate()
    session_id = "sess-arch-004"

    blueprint = gate.generate_execution_blueprint(
        session_id=session_id,
        selected_option_id="opt-tiptap",
        title="Implementation Plan",
        steps=[
            ExecutionBlueprintStep(
                step_id="step-1",
                order=1,
                title="Init",
                description="Init project structure",
                acceptance_criteria=("done",),
                affected_components=(),
            )
        ],
    )

    # Prior to approval, tools must be suppressed
    assert gate.is_tool_allowed(session_id, "write_file")[0] is False

    # User approves and locks plan
    eval_result = gate.approve_and_lock_plan(session_id, blueprint.blueprint_id)

    assert eval_result.current_mode == ArchitectureMode.EXECUTION_LOCKED
    assert eval_result.destructive_tools_suppressed is False
    assert eval_result.active_blueprint is not None
    assert eval_result.active_blueprint.is_approved_by_user is True
    assert eval_result.active_blueprint.approved_at is not None

    # Write tools must now be permitted
    allowed, _ = gate.is_tool_allowed(session_id, "write_file")
    assert allowed is True
    allowed_replace, _ = gate.is_tool_allowed(session_id, "replace_file_content")
    assert allowed_replace is True

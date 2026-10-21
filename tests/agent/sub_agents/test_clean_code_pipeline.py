"""Unit tests for Clean Code Assembly Pipeline & Architecture Dependency Linter (Item 62).

[INPUT]
- CleanCodeAssemblyPipelineEngine and ArchitectureDependencyLinter.

[OUTPUT]
- Pytest assertions validating 5-stage progression, layer enforcement,
  cycle detection, and DIP remediation.

[POS]
- myrm-agent-harness/tests/agent/sub_agents/test_clean_code_pipeline.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.clean_code_pipeline import (
    ArchitectureDependencyLinter,
    CleanCodeAssemblyPipelineEngine,
    PipelineStage,
    StageStatus,
    ViolationType,
)


@pytest.fixture
def linter() -> ArchitectureDependencyLinter:
    """Fixture providing a fresh ArchitectureDependencyLinter instance."""
    return ArchitectureDependencyLinter()


@pytest.fixture
def engine(linter: ArchitectureDependencyLinter) -> CleanCodeAssemblyPipelineEngine:
    """Fixture providing a fresh CleanCodeAssemblyPipelineEngine instance."""
    eng = CleanCodeAssemblyPipelineEngine(linter=linter)
    eng.clear()
    return eng


def test_architecture_dependency_linter_clean_code(
    linter: ArchitectureDependencyLinter,
) -> None:
    """Test that compliant unidirectional dependencies pass static architecture linting."""
    modules = {
        "src/ui/chat_view.py": "import src.application.chat_service\nimport src.schemas.chat_dto",
        "src/application/chat_service.py": "import src.domain.chat_aggregate\nimport src.schemas.chat_dto",
        "src/domain/chat_aggregate.py": "import src.schemas.chat_dto\n# Pure business domain logic",
        "src/infrastructure/chat_repository.py": "import src.domain.chat_aggregate",
    }
    result = linter.lint_project_modules(modules)
    assert result.is_valid
    assert len(result.violations) == 0
    assert result.scanned_files_count == 4


def test_architecture_dependency_linter_inverted_dependency(
    linter: ArchitectureDependencyLinter,
) -> None:
    """Test that Domain importing outer UI/Infra layers triggers INVERTED_DEPENDENCY with DIP advice."""
    # Bad architectural smell: Domain directly importing UI router and Infra DB adapter!
    domain_code = """
import src.ui.chat_view
import src.infrastructure.chat_repository

class OrderDomain:
    def process(self):
        pass
"""
    result = linter.lint_module_code("src/domain/order.py", domain_code)
    assert not result.is_valid
    assert len(result.violations) == 2

    # Check violation types and DIP remediation guidance
    for v in result.violations:
        assert v.violation_type == ViolationType.INVERTED_DEPENDENCY
        assert "Domain layer" in v.rule_description
        assert "Apply DIP" in v.remediation_suggestion


def test_architecture_dependency_linter_circular_dependency(
    linter: ArchitectureDependencyLinter,
) -> None:
    """Test detection of circular dependencies across multi-module graphs."""
    modules = {
        "src/services/billing.py": "import src.services.invoice",
        "src/services/invoice.py": "import src.services.billing",
    }
    result = linter.lint_project_modules(modules)
    assert not result.is_valid
    cycle_violations = [v for v in result.violations if v.violation_type == ViolationType.CIRCULAR_DEPENDENCY]
    assert len(cycle_violations) >= 1
    assert "Circular dependency detected" in cycle_violations[0].rule_description


def test_clean_code_pipeline_full_5_stage_progression(
    engine: CleanCodeAssemblyPipelineEngine,
) -> None:
    """Test full sequential progression through the 5 Clean Code stages."""
    task_id = "task-clean-01"
    task = engine.start_pipeline(
        task_id=task_id,
        title="JWT Token Rotation Service",
        spec_prompt="Implement secure JWT rotation with redis refresh storage",
    )
    assert task.current_stage == PipelineStage.SPECIFIER
    assert task.status == StageStatus.RUNNING

    # Stage 1: Specifier submits BDD contract
    task = engine.advance_stage(
        task_id=task_id,
        artifact_title="Gherkin Acceptance Scenarios",
        artifact_content="Feature: JWT Rotation\nScenario: Valid refresh token",
    )
    assert task.current_stage == PipelineStage.CODER
    assert "specifier" in task.artifacts
    assert task.artifacts["specifier"].title == "Gherkin Acceptance Scenarios"

    # Stage 2: Coder submits deep module implementation
    task = engine.advance_stage(
        task_id=task_id,
        artifact_title="Deep Module Core Code",
        artifact_content="class TokenRotationService: ...",
    )
    assert task.current_stage == PipelineStage.CLEANER
    assert "coder" in task.artifacts

    # Stage 3: Cleaner submits refactored code with low CRAP index
    task = engine.advance_stage(
        task_id=task_id,
        artifact_title="Clean Refactored Code",
        artifact_content="CRAP score: 2.1; 0 code smells",
    )
    assert task.current_stage == PipelineStage.HARDENER
    assert "cleaner" in task.artifacts

    # Stage 4: Hardener submits mutation-tested edge test cases
    task = engine.advance_stage(
        task_id=task_id,
        artifact_title="Mutation Resilient Test Suite",
        artifact_content="100% mutant kill rate on boundary exceptions",
    )
    assert task.current_stage == PipelineStage.QA
    assert "hardener" in task.artifacts

    # Stage 5: QA signs off after running E2E acceptance tests
    task = engine.advance_stage(
        task_id=task_id,
        artifact_title="Final E2E Sign-off Report",
        artifact_content="All 5 BDD acceptance criteria passed",
    )
    assert task.current_stage == PipelineStage.QA
    assert task.status == StageStatus.COMPLETED
    assert "qa" in task.artifacts
    assert len(task.stage_history) == 5


def test_clean_code_pipeline_gate_blocked_by_linter(
    engine: CleanCodeAssemblyPipelineEngine,
) -> None:
    """Test that architectural violations block the pipeline from completing."""
    task_id = "task-gate-02"
    engine.start_pipeline(task_id, "Order Module", "Build order aggregate")

    # Move to Coder stage
    engine.advance_stage(task_id, "Spec", "Contract")

    # Code has invalid reverse dependency
    invalid_code_map = {
        "src/domain/order.py": "import src.ui.web_view\nclass Order: pass",
    }
    lint_result = engine.lint_and_gate_check(task_id, invalid_code_map)
    assert not lint_result.is_valid
    task = engine.get_task(task_id)
    assert task is not None
    assert task.status == StageStatus.BLOCKED
    assert "arch_lint_report" in task.artifacts

    # Now fix code following DIP
    fixed_code_map = {
        "src/domain/order.py": "import src.schemas.order_dto\nclass Order: pass",
    }
    fixed_result = engine.lint_and_gate_check(task_id, fixed_code_map)
    assert fixed_result.is_valid

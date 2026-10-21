"""Unit tests for Planner-Generator-Evaluator Tri-Role Separation & Artifact Handoff Pipeline.

[INPUT]
- myrm_agent_harness.agent.coordination.tri_role::{
    AcceptanceCriterion,
    ArtifactManifest,
    EvaluationVerdict,
    StageStatus,
    TriRolePipelineCoordinator,
    TriRolePipelineError,
    TriRolePipelineStage,
    TriRoleSessionState,
    TriRoleType,
  }

[OUTPUT]
- Pytest cases verifying tri-role separation, cognitive isolation, criteria-driven
  evaluation, rejection/acceptance branching, and cross-session artifact handoff.

[POS]
- myrm-agent-harness/tests/agent/coordination/test_tri_role.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.coordination.tri_role import (
    AcceptanceCriterion,
    StageStatus,
    TriRolePipelineCoordinator,
    TriRolePipelineError,
    TriRoleType,
)


@pytest.fixture
def coordinator() -> TriRolePipelineCoordinator:
    return TriRolePipelineCoordinator()


def test_create_session_success(coordinator: TriRolePipelineCoordinator) -> None:
    session = coordinator.create_session(
        session_id="sess_tri_1",
        task_description="Build Auth Microservice",
        stage_names=["Architecture Plan", "Implementation", "Security Audit"],
    )
    assert session.session_id == "sess_tri_1"
    assert session.task_description == "Build Auth Microservice"
    assert len(session.stages) == 3
    assert session.current_stage_index == 0
    assert session.is_completed is False
    assert session.stages[0].status == StageStatus.PLANNED


def test_create_session_validation_errors(
    coordinator: TriRolePipelineCoordinator,
) -> None:
    with pytest.raises(TriRolePipelineError, match="Session ID cannot be empty"):
        coordinator.create_session("", "Task", ["Stage1"])

    with pytest.raises(
        TriRolePipelineError, match="At least one stage name must be provided"
    ):
        coordinator.create_session("sess_err", "Task", [])


def test_planner_submission_flow(coordinator: TriRolePipelineCoordinator) -> None:
    session = coordinator.create_session(
        session_id="sess_plan",
        task_description="Setup Database",
        stage_names=["Migration"],
    )
    stage_id = session.stages[0].stage_id

    criterion = AcceptanceCriterion(
        criterion_id="crit_1",
        description="Must have users table schema",
        assertion_rule="table_exists('users')",
    )

    stage = coordinator.submit_plan(
        session_id="sess_plan",
        stage_id=stage_id,
        planner_output="Planned schema migration with SQL.",
        criteria=[criterion],
    )
    assert stage.status == StageStatus.GENERATING
    assert len(stage.criteria) == 1
    assert stage.planner_output == "Planned schema migration with SQL."


def test_generator_submission_flow(coordinator: TriRolePipelineCoordinator) -> None:
    session = coordinator.create_session(
        session_id="sess_gen",
        task_description="Implement API",
        stage_names=["API Stage"],
    )
    stage_id = session.stages[0].stage_id

    criterion = AcceptanceCriterion(
        criterion_id="crit_api",
        description="Endpoint /health returns 200",
        assertion_rule="GET /health == 200",
    )
    coordinator.submit_plan("sess_gen", stage_id, "Plan API", [criterion])

    stage = coordinator.submit_generation(
        session_id="sess_gen",
        stage_id=stage_id,
        generator_output="FastAPI endpoint implemented.",
        produced_files=["api.py", "test_api.py"],
    )
    assert stage.status == StageStatus.EVALUATING
    assert stage.produced_files == ["api.py", "test_api.py"]


def test_evaluator_verdict_accepted_creates_manifest(
    coordinator: TriRolePipelineCoordinator,
) -> None:
    session = coordinator.create_session(
        session_id="sess_eval_ok",
        task_description="Build Cache",
        stage_names=["Redis Cache"],
    )
    stage_id = session.stages[0].stage_id

    crit1 = AcceptanceCriterion("c1", "Redis client configured", "redis_conn is not None")
    crit2 = AcceptanceCriterion("c2", "TTL set to 300s", "ttl == 300")

    coordinator.submit_plan("sess_eval_ok", stage_id, "Plan Cache", [crit1, crit2])
    coordinator.submit_generation(
        "sess_eval_ok", stage_id, "Code cache", ["cache.py"]
    )

    verdict = coordinator.evaluate_stage(
        session_id="sess_eval_ok",
        stage_id=stage_id,
        evaluator_notes="All acceptance criteria verified in test run.",
        criteria_evaluations={"c1": True, "c2": True},
        min_pass_rate=1.0,
    )

    assert verdict.is_accepted is True
    assert verdict.score == 1.0

    updated_session = coordinator.get_session("sess_eval_ok")
    assert updated_session is not None
    stage = updated_session.stages[0]
    assert stage.status == StageStatus.ACCEPTED
    assert stage.manifest is not None
    assert stage.manifest.produced_files == ["cache.py"]
    assert "Redis client configured" in stage.manifest.passed_assertions


def test_evaluator_verdict_rejection(coordinator: TriRolePipelineCoordinator) -> None:
    session = coordinator.create_session(
        session_id="sess_eval_fail",
        task_description="Build Cache",
        stage_names=["Redis Cache"],
    )
    stage_id = session.stages[0].stage_id

    crit1 = AcceptanceCriterion("c1", "Redis client configured", "redis_conn is not None")
    coordinator.submit_plan("sess_eval_fail", stage_id, "Plan Cache", [crit1])
    coordinator.submit_generation(
        "sess_eval_fail", stage_id, "Buggy code", ["cache.py"]
    )

    verdict = coordinator.evaluate_stage(
        session_id="sess_eval_fail",
        stage_id=stage_id,
        evaluator_notes="Failed connection assertion.",
        criteria_evaluations={"c1": False},
        min_pass_rate=1.0,
    )
    assert verdict.is_accepted is False
    assert verdict.score == 0.0

    updated_session = coordinator.get_session("sess_eval_fail")
    assert updated_session is not None
    assert updated_session.stages[0].status == StageStatus.REJECTED
    assert updated_session.stages[0].manifest is None


def test_stage_advancement_and_completion(
    coordinator: TriRolePipelineCoordinator,
) -> None:
    session = coordinator.create_session(
        session_id="sess_multi",
        task_description="Multi Stage Task",
        stage_names=["Stage 1", "Stage 2"],
    )
    s1_id = session.stages[0].stage_id
    crit = AcceptanceCriterion("c1", "C1 passed", "rule")
    coordinator.submit_plan("sess_multi", s1_id, "P1", [crit])
    coordinator.submit_generation("sess_multi", s1_id, "G1", ["f1.py"])
    coordinator.evaluate_stage("sess_multi", s1_id, "E1 ok", {"c1": True})

    # Advance to Stage 2
    session_after_s1 = coordinator.advance_to_next_stage("sess_multi")
    assert session_after_s1.current_stage_index == 1
    assert session_after_s1.is_completed is False

    s2_id = session_after_s1.stages[1].stage_id
    coordinator.submit_plan("sess_multi", s2_id, "P2", [crit])
    coordinator.submit_generation("sess_multi", s2_id, "G2", ["f2.py"])
    coordinator.evaluate_stage("sess_multi", s2_id, "E2 ok", {"c1": True})

    # Advance completing the session
    session_completed = coordinator.advance_to_next_stage("sess_multi")
    assert session_completed.current_stage_index == 2
    assert session_completed.is_completed is True


def test_cross_session_manifest_handoff_and_restore(
    coordinator: TriRolePipelineCoordinator,
) -> None:
    session = coordinator.create_session(
        session_id="sess_session_a",
        task_description="Module A Development",
        stage_names=["Phase 1", "Phase 2"],
    )
    s1_id = session.stages[0].stage_id
    crit = AcceptanceCriterion("c_handoff", "Interface contract verified", "contract == OK")
    coordinator.submit_plan("sess_session_a", s1_id, "Plan Phase 1", [crit])
    coordinator.submit_generation("sess_session_a", s1_id, "Gen Phase 1", ["mod_a.py"])
    coordinator.evaluate_stage("sess_session_a", s1_id, "Accepted", {"c_handoff": True})

    manifest = coordinator.export_handoff_manifest("sess_session_a")
    assert manifest.session_id == "sess_session_a"
    assert manifest.produced_files == ["mod_a.py"]
    assert "Interface contract verified" in manifest.passed_assertions

    # Restore in Session B
    new_session = coordinator.restore_session_from_manifest(
        manifest=manifest,
        new_session_id="sess_session_b",
        task_description="Module B Development Continuing from A",
        subsequent_stage_names=["Phase 3 Integration"],
    )
    assert new_session.session_id == "sess_session_b"
    assert len(new_session.stages) == 2  # 1 imported baseline + 1 subsequent
    assert new_session.stages[0].status == StageStatus.ACCEPTED
    assert new_session.stages[0].produced_files == ["mod_a.py"]
    assert new_session.current_stage_index == 1
    assert new_session.stages[1].stage_name == "Phase 3 Integration"
    assert new_session.stages[1].status == StageStatus.PLANNED


def test_tri_role_type_enum() -> None:
    assert TriRoleType.PLANNER == "planner"
    assert TriRoleType.GENERATOR == "generator"
    assert TriRoleType.EVALUATOR == "evaluator"

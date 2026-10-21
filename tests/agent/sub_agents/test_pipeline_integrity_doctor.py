"""Unit tests for PipelineIntegrityDoctor in Harness layer.

Validates gap detection (metadata, approval gate, publish artifact, verification step),
decision chain inspection, and automated healing functionality.
"""

from myrm_agent_harness.agent.sub_agents.pipeline_integrity import (
    GapCategory,
    GapSeverity,
    HandoffMetadata,
    HandoffStep,
    PipelineDefinition,
    PipelineIntegrityDoctor,
    StepStage,
)


def test_healthy_pipeline_lint() -> None:
    """Verifies that a fully configured, compliant pipeline produces no gaps."""
    doctor = PipelineIntegrityDoctor()
    pipeline = PipelineDefinition(
        pipeline_id="pipe-healthy-01",
        name="Healthy Full Lifecycle Pipeline",
        steps=[
            HandoffStep(
                step_id="step-route",
                stage=StepStage.ROUTING,
                agent_role="orchestrator",
                requires_approval=False,
                requires_verification=False,
            ),
            HandoffStep(
                step_id="step-exec",
                stage=StepStage.EXECUTION,
                agent_role="coder",
                requires_approval=False,
                requires_verification=True,
                metadata=HandoffMetadata(
                    source_agent="orchestrator",
                    target_agent="coder",
                    transfer_reason="Execute code changes",
                ),
            ),
            HandoffStep(
                step_id="step-review",
                stage=StepStage.REVIEW,
                agent_role="reviewer",
                requires_approval=True,
                metadata=HandoffMetadata(
                    source_agent="coder",
                    target_agent="reviewer",
                    transfer_reason="Review PR diff",
                ),
            ),
            HandoffStep(
                step_id="step-deliver",
                stage=StepStage.DELIVERY,
                agent_role="deployer",
                requires_approval=False,
                requires_verification=False,
                produced_artifacts=["bundle_v1.tar.gz"],
                metadata=HandoffMetadata(
                    source_agent="reviewer",
                    target_agent="deployer",
                    transfer_reason="Publish production artifact",
                ),
            ),
        ],
    )

    report = doctor.lint_pipeline(pipeline)
    assert report.pipeline_id == "pipe-healthy-01"
    assert report.total_steps == 4
    assert report.is_healthy is True
    assert len(report.gaps) == 0
    assert len(report.decision_chain) == 4


def test_missing_handoff_metadata_gap() -> None:
    """Verifies RULE-001: Missing handoff metadata across different agent roles."""
    doctor = PipelineIntegrityDoctor()
    pipeline = PipelineDefinition(
        pipeline_id="pipe-no-metadata",
        name="Pipeline with Missing Handoff Metadata",
        steps=[
            HandoffStep(
                step_id="step-1",
                stage=StepStage.ANALYSIS,
                agent_role="architect",
            ),
            HandoffStep(
                step_id="step-2",
                stage=StepStage.EXECUTION,
                agent_role="coder",
                # Omitted metadata while switching from architect to coder!
            ),
        ],
    )

    report = doctor.lint_pipeline(pipeline)
    metadata_gaps = [
        g for g in report.gaps if g.category == GapCategory.MISSING_HANDOFF_METADATA
    ]
    assert len(metadata_gaps) == 1
    diag = metadata_gaps[0]
    assert diag.rule_id == "RULE-001-HANDOFF-METADATA"
    assert diag.severity == GapSeverity.WARNING
    assert "architect" in diag.message and "coder" in diag.message


def test_missing_approval_gate_before_delivery() -> None:
    """Verifies RULE-002: Missing approval gate before reaching delivery stage."""
    doctor = PipelineIntegrityDoctor()
    pipeline = PipelineDefinition(
        pipeline_id="pipe-no-approval",
        name="Pipeline Direct to Delivery",
        steps=[
            HandoffStep(
                step_id="step-exec",
                stage=StepStage.EXECUTION,
                agent_role="coder",
                requires_verification=True,
            ),
            HandoffStep(
                step_id="step-deliver",
                stage=StepStage.DELIVERY,
                agent_role="deployer",
                requires_approval=False,
                produced_artifacts=["dist.zip"],
                metadata=HandoffMetadata(
                    source_agent="coder",
                    target_agent="deployer",
                    transfer_reason="Fast-track release",
                ),
            ),
        ],
    )

    report = doctor.lint_pipeline(pipeline)
    approval_gaps = [
        g for g in report.gaps if g.category == GapCategory.MISSING_APPROVAL_GATE
    ]
    assert len(approval_gaps) == 1
    diag = approval_gaps[0]
    assert diag.rule_id == "RULE-002-APPROVAL-GATE"
    assert diag.severity == GapSeverity.ERROR
    assert report.is_healthy is False


def test_missing_publish_artifact_at_delivery() -> None:
    """Verifies RULE-003: Delivery step producing no artifacts."""
    doctor = PipelineIntegrityDoctor()
    pipeline = PipelineDefinition(
        pipeline_id="pipe-empty-artifacts",
        name="Pipeline with Empty Artifact Delivery",
        steps=[
            HandoffStep(
                step_id="step-review",
                stage=StepStage.REVIEW,
                agent_role="lead",
                requires_approval=True,
                requires_verification=True,
            ),
            HandoffStep(
                step_id="step-deliver",
                stage=StepStage.DELIVERY,
                agent_role="deployer",
                produced_artifacts=[],  # Empty!
                metadata=HandoffMetadata(
                    source_agent="lead",
                    target_agent="deployer",
                    transfer_reason="Publish",
                ),
            ),
        ],
    )

    report = doctor.lint_pipeline(pipeline)
    artifact_gaps = [
        g for g in report.gaps if g.category == GapCategory.MISSING_PUBLISH_ARTIFACT
    ]
    assert len(artifact_gaps) == 1
    diag = artifact_gaps[0]
    assert diag.rule_id == "RULE-003-PUBLISH-ARTIFACT"
    assert diag.severity == GapSeverity.ERROR


def test_missing_verification_step_before_delivery() -> None:
    """Verifies RULE-004: Omission of test or verification step prior to delivery."""
    doctor = PipelineIntegrityDoctor()
    pipeline = PipelineDefinition(
        pipeline_id="pipe-no-test",
        name="Pipeline Skipping Verification",
        steps=[
            HandoffStep(
                step_id="step-review",
                stage=StepStage.REVIEW,
                agent_role="lead",
                requires_approval=True,
                requires_verification=False,  # Skipped!
            ),
            HandoffStep(
                step_id="step-deliver",
                stage=StepStage.DELIVERY,
                agent_role="deployer",
                produced_artifacts=["package.whl"],
                metadata=HandoffMetadata(
                    source_agent="lead",
                    target_agent="deployer",
                    transfer_reason="Publish",
                ),
            ),
        ],
    )

    report = doctor.lint_pipeline(pipeline)
    verif_gaps = [
        g for g in report.gaps if g.category == GapCategory.MISSING_VERIFICATION_STEP
    ]
    assert len(verif_gaps) == 1
    diag = verif_gaps[0]
    assert diag.rule_id == "RULE-004-VERIFICATION-STEP"
    assert diag.severity == GapSeverity.WARNING


def test_inspect_decision_chain_structure() -> None:
    """Verifies transparent decision chain extraction."""
    doctor = PipelineIntegrityDoctor()
    steps = [
        HandoffStep(
            step_id="s1",
            stage=StepStage.ROUTING,
            agent_role="router",
        ),
        HandoffStep(
            step_id="s2",
            stage=StepStage.EXECUTION,
            agent_role="coder",
            metadata=HandoffMetadata(
                source_agent="router",
                target_agent="coder",
                transfer_reason="Assigned task implementation",
            ),
        ),
    ]

    chain = doctor.inspect_decision_chain(steps)
    assert len(chain) == 2
    assert chain[0].to_role == "router"
    assert chain[1].from_role == "router"
    assert chain[1].to_role == "coder"
    assert chain[1].reason == "Assigned task implementation"


def test_auto_heal_pipeline() -> None:
    """Verifies automated healing of diagnosed gaps into a compliant pipeline."""
    doctor = PipelineIntegrityDoctor()
    broken_pipeline = PipelineDefinition(
        pipeline_id="pipe-broken",
        name="Completely Broken Pipeline",
        steps=[
            HandoffStep(
                step_id="s1",
                stage=StepStage.EXECUTION,
                agent_role="coder",
                requires_approval=False,
                requires_verification=False,
            ),
            HandoffStep(
                step_id="s2",
                stage=StepStage.DELIVERY,
                agent_role="deployer",
                requires_approval=False,
                requires_verification=False,
                produced_artifacts=[],
            ),
        ],
    )

    initial_report = doctor.lint_pipeline(broken_pipeline)
    assert initial_report.is_healthy is False
    assert len(initial_report.gaps) >= 3

    # Auto-heal
    healed = doctor.auto_heal_pipeline(broken_pipeline)
    assert "+healed" in healed.version

    healed_report = doctor.lint_pipeline(healed)
    assert healed_report.is_healthy is True
    # Zero error gaps remaining
    error_gaps = [g for g in healed_report.gaps if g.severity == GapSeverity.ERROR]
    assert len(error_gaps) == 0
    # Artifact was provided automatically
    delivery_step = next(s for s in healed.steps if s.stage == StepStage.DELIVERY)
    assert len(delivery_step.produced_artifacts) > 0
    assert delivery_step.requires_approval is True

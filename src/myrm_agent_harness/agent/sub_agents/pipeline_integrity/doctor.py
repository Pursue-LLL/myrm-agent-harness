"""Pipeline Integrity Doctor Engine.

Inspects multi-agent workflows, spot handoff gaps, verifies approval gates,
validates publish artifacts, ensures verification steps, and generates
transparent, inspectable decision chains.

[INPUT]
- __future__
- time

[OUTPUT]
- PipelineIntegrityDoctor

[POS]
Pipeline Integrity Doctor Engine.
"""

from __future__ import annotations

import time

from myrm_agent_harness.agent.sub_agents.pipeline_integrity.types import (
    DecisionChainLink,
    GapCategory,
    GapSeverity,
    HandoffGapDiagnostic,
    HandoffMetadata,
    HandoffStep,
    PipelineDefinition,
    PipelineIntegrityDoctorReport,
    StepStage,
)


class PipelineIntegrityDoctor:
    """Diagnostic doctor that inspects multi-agent workflows for pipeline integrity gaps."""

    def __init__(self) -> None:
        """Initialize the pipeline integrity doctor with standard integrity rules."""
        pass

    def lint_pipeline(self, pipeline: PipelineDefinition) -> PipelineIntegrityDoctorReport:
        """Perform a comprehensive lint check across all steps in the pipeline definition.

        Identifies missing handoff metadata, omitted approval gates, missing publish artifacts,
        and lack of verification steps before delivery.
        """
        gaps: list[HandoffGapDiagnostic] = []
        steps = pipeline.steps
        has_delivery_step = any(step.stage == StepStage.DELIVERY for step in steps)
        has_approval_gate = any(step.requires_approval or step.stage == StepStage.REVIEW for step in steps)
        has_verification_step = any(
            step.requires_verification or step.stage == StepStage.VERIFICATION for step in steps
        )

        prev_step: HandoffStep | None = None
        for idx, step in enumerate(steps):
            # RULE-001: Check Handoff Metadata
            if (
                idx > 0
                and prev_step is not None
                and step.agent_role != prev_step.agent_role
                and (step.metadata is None or not step.metadata.transfer_reason.strip())
            ):
                gaps.append(
                    HandoffGapDiagnostic(
                        rule_id="RULE-001-HANDOFF-METADATA",
                        category=GapCategory.MISSING_HANDOFF_METADATA,
                        severity=GapSeverity.WARNING,
                        step_id=step.step_id,
                        message=(
                            f"Step '{step.step_id}' delegates from '{prev_step.agent_role}' "
                            f"to '{step.agent_role}' without handoff metadata or transfer reason."
                        ),
                        suggested_fix=(
                            f"Attach HandoffMetadata specifying source_agent='{prev_step.agent_role}', "
                            f"target_agent='{step.agent_role}', and a non-empty transfer_reason."
                        ),
                    )
                )

            # RULE-003: Check Publish Artifact at Delivery
            if step.stage == StepStage.DELIVERY and not step.produced_artifacts:
                gaps.append(
                    HandoffGapDiagnostic(
                        rule_id="RULE-003-PUBLISH-ARTIFACT",
                        category=GapCategory.MISSING_PUBLISH_ARTIFACT,
                        severity=GapSeverity.ERROR,
                        step_id=step.step_id,
                        message=(
                            f"Delivery step '{step.step_id}' produces no declared artifacts. "
                            "Downstream consumers cannot verify publish contract."
                        ),
                        suggested_fix="Declare at least one produced artifact identifier in produced_artifacts.",
                    )
                )

            prev_step = step

        # RULE-002: Check Approval Gate before Delivery
        if has_delivery_step and not has_approval_gate:
            delivery_step_id = next(s.step_id for s in steps if s.stage == StepStage.DELIVERY)
            gaps.append(
                HandoffGapDiagnostic(
                    rule_id="RULE-002-APPROVAL-GATE",
                    category=GapCategory.MISSING_APPROVAL_GATE,
                    severity=GapSeverity.ERROR,
                    step_id=delivery_step_id,
                    message="Pipeline proceeds directly to Delivery without an explicit IN_REVIEW or approval gate.",
                    suggested_fix="Insert a Review step or set requires_approval=True prior to final delivery.",
                )
            )

        # RULE-004: Check Verification Step before Delivery
        if has_delivery_step and not has_verification_step:
            delivery_step_id = next(s.step_id for s in steps if s.stage == StepStage.DELIVERY)
            gaps.append(
                HandoffGapDiagnostic(
                    rule_id="RULE-004-VERIFICATION-STEP",
                    category=GapCategory.MISSING_VERIFICATION_STEP,
                    severity=GapSeverity.WARNING,
                    step_id=delivery_step_id,
                    message="Pipeline reaches Delivery without a dedicated verification or test execution phase.",
                    suggested_fix="Introduce a verification step or set requires_verification=True on the execution step.",
                )
            )

        decision_chain = self.inspect_decision_chain(steps)
        is_healthy = len([g for g in gaps if g.severity == GapSeverity.ERROR]) == 0

        return PipelineIntegrityDoctorReport(
            pipeline_id=pipeline.pipeline_id,
            total_steps=len(steps),
            is_healthy=is_healthy,
            gaps=gaps,
            decision_chain=decision_chain,
            scanned_at=time.time(),
        )

    def inspect_decision_chain(self, steps: list[HandoffStep]) -> list[DecisionChainLink]:
        """Extract a transparent, inspectable chain of delegation and routing decisions."""
        chain: list[DecisionChainLink] = []
        prev_role = "user"
        for step in steps:
            from_role = step.metadata.source_agent if step.metadata else prev_role
            to_role = step.agent_role
            reason = (
                step.metadata.transfer_reason
                if step.metadata and step.metadata.transfer_reason
                else f"Proceed to stage {step.stage.value}"
            )
            chain.append(
                DecisionChainLink(
                    step_id=step.step_id,
                    from_role=from_role,
                    to_role=to_role,
                    stage=step.stage,
                    reason=reason,
                )
            )
            prev_role = step.agent_role
        return chain

    def auto_heal_pipeline(self, pipeline: PipelineDefinition) -> PipelineDefinition:
        """Automatically synthesize remedies for diagnosed integrity gaps.

        Fixes missing handoff metadata, ensures approval gates exist before delivery,
        adds verification requirement, and defaults delivery artifact contracts.
        """
        report = self.lint_pipeline(pipeline)
        if not report.gaps:
            return pipeline

        new_steps: list[HandoffStep] = []
        prev_role = "user"

        for step in pipeline.steps:
            current_metadata = step.metadata
            # Fix Missing Handoff Metadata
            if (
                prev_role != "user"
                and prev_role != step.agent_role
                and (current_metadata is None or not current_metadata.transfer_reason.strip())
            ):
                current_metadata = HandoffMetadata(
                    source_agent=prev_role,
                    target_agent=step.agent_role,
                    transfer_reason=f"Delegated from {prev_role} to {step.agent_role} for {step.stage.value}",
                    context_keys=["session_context", "task_spec"],
                )


            # Fix Missing Verification & Approval on steps preceding or at Delivery
            new_requires_approval = step.requires_approval
            new_requires_verification = step.requires_verification
            new_artifacts = list(step.produced_artifacts)

            if step.stage == StepStage.DELIVERY:
                if not new_artifacts:
                    new_artifacts = [f"artifact_{step.step_id}_bundle.json"]
                new_requires_approval = True
            elif step.stage in (StepStage.EXECUTION, StepStage.ANALYSIS):
                # Ensure verification flag is enabled if no verification step exists
                new_requires_verification = True

            new_steps.append(
                HandoffStep(
                    step_id=step.step_id,
                    stage=step.stage,
                    agent_role=step.agent_role,
                    requires_approval=new_requires_approval,
                    requires_verification=new_requires_verification,
                    produced_artifacts=new_artifacts,
                    metadata=current_metadata,
                )
            )
            prev_role = step.agent_role

        return PipelineDefinition(
            pipeline_id=pipeline.pipeline_id,
            name=f"{pipeline.name} (Auto-Healed)",
            steps=new_steps,
            version=f"{pipeline.version}+healed",
        )

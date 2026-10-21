"""Tri-Role Pipeline Coordinator implementing cognitive separation and artifact handoff.

[INPUT]
- Sessions, stages, planner acceptance criteria, generator output, evaluator assertions,
  and artifact handoff manifests.

[OUTPUT]
- Deterministic stage progression, independent verification verdicts, and cross-session
  lossless handoff state.

[POS]
- Harness coordination layer orchestrator for Planner-Generator-Evaluator separation (Item 40).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

from .types import (
    AcceptanceCriterion,
    ArtifactManifest,
    EvaluationVerdict,
    StageStatus,
    TriRolePipelineStage,
    TriRoleSessionState,
)


class TriRolePipelineError(ValueError):
    """Raised when an invalid state transition or operation occurs in tri-role pipeline."""


class TriRolePipelineCoordinator:
    """Coordinates Planner-Generator-Evaluator multi-agent pipelines with zero-loss handoff."""

    def __init__(self) -> None:
        self._sessions: dict[str, TriRoleSessionState] = {}

    def create_session(
        self,
        session_id: str,
        task_description: str,
        stage_names: list[str],
    ) -> TriRoleSessionState:
        """Create a new tri-role session partitioned into sequential discrete horizon stages."""
        if not session_id:
            msg = "Session ID cannot be empty."
            raise TriRolePipelineError(msg)
        if not stage_names:
            msg = "At least one stage name must be provided."
            raise TriRolePipelineError(msg)

        stages = [
            TriRolePipelineStage(
                stage_id=f"{session_id}_stage_{idx}",
                stage_name=name,
                status=StageStatus.PLANNED,
            )
            for idx, name in enumerate(stage_names)
        ]
        now = datetime.now(tz=UTC)
        state = TriRoleSessionState(
            session_id=session_id,
            task_description=task_description,
            stages=stages,
            current_stage_index=0,
            is_completed=False,
            created_at=now,
            updated_at=now,
        )
        self._sessions[session_id] = state
        return state

    def get_session(self, session_id: str) -> TriRoleSessionState | None:
        """Retrieve existing tri-role session state by session ID."""
        return self._sessions.get(session_id)

    def submit_plan(
        self,
        session_id: str,
        stage_id: str,
        planner_output: str,
        criteria: list[AcceptanceCriterion],
    ) -> TriRolePipelineStage:
        """Record Planner output and acceptance criteria, advancing stage to GENERATING."""
        session = self._require_session(session_id)
        stage_idx, stage = self._find_stage(session, stage_id)

        if stage.status not in (StageStatus.PLANNED, StageStatus.REJECTED):
            msg = f"Stage '{stage_id}' is in status '{stage.status}', cannot accept new plan."
            raise TriRolePipelineError(msg)
        if not criteria:
            msg = "Planner must formulate at least one acceptance criterion."
            raise TriRolePipelineError(msg)

        updated_stage = dataclasses.replace(
            stage,
            status=StageStatus.GENERATING,
            planner_output=planner_output,
            criteria=criteria,
        )
        self._update_stage_in_session(session, stage_idx, updated_stage)
        return updated_stage

    def submit_generation(
        self,
        session_id: str,
        stage_id: str,
        generator_output: str,
        produced_files: list[str],
    ) -> TriRolePipelineStage:
        """Record Generator deliverables, advancing stage to EVALUATING."""
        session = self._require_session(session_id)
        stage_idx, stage = self._find_stage(session, stage_id)

        if stage.status != StageStatus.GENERATING:
            msg = f"Stage '{stage_id}' is in status '{stage.status}', cannot accept generation."
            raise TriRolePipelineError(msg)

        updated_stage = dataclasses.replace(
            stage,
            status=StageStatus.EVALUATING,
            generator_output=generator_output,
            produced_files=list(produced_files),
        )
        self._update_stage_in_session(session, stage_idx, updated_stage)
        return updated_stage

    def evaluate_stage(
        self,
        session_id: str,
        stage_id: str,
        evaluator_notes: str,
        criteria_evaluations: dict[str, bool],
        min_pass_rate: float = 1.0,
    ) -> EvaluationVerdict:
        """Evaluate generation deliverables against criteria independently from Generator."""
        session = self._require_session(session_id)
        stage_idx, stage = self._find_stage(session, stage_id)

        if stage.status != StageStatus.EVALUATING:
            msg = f"Stage '{stage_id}' is in status '{stage.status}', cannot be evaluated."
            raise TriRolePipelineError(msg)

        # Calculate acceptance score based on criteria verification
        total_criteria = len(stage.criteria)
        if total_criteria == 0:
            score = 1.0
            is_accepted = True
        else:
            satisfied_count = 0
            for crit in stage.criteria:
                if criteria_evaluations.get(crit.criterion_id, False):
                    satisfied_count += 1
            score = satisfied_count / total_criteria
            is_accepted = score >= min_pass_rate

        verdict = EvaluationVerdict(
            is_accepted=is_accepted,
            score=score,
            evaluator_notes=evaluator_notes,
            criteria_results=dict(criteria_evaluations),
            evaluated_at=datetime.now(tz=UTC),
        )

        manifest: ArtifactManifest | None = None
        new_status = StageStatus.ACCEPTED if is_accepted else StageStatus.REJECTED

        if is_accepted:
            # Package verified stage into ArtifactManifest
            passed_criteria = [
                crit.description
                for crit in stage.criteria
                if criteria_evaluations.get(crit.criterion_id, False)
            ]
            manifest = ArtifactManifest(
                manifest_id=f"manifest_{stage.stage_id}_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                stage_index=stage_idx,
                produced_files=list(stage.produced_files),
                passed_assertions=passed_criteria,
                key_constraints=[c.assertion_rule for c in stage.criteria],
                pending_todos=[],
                created_at=datetime.now(tz=UTC),
            )

        updated_stage = dataclasses.replace(
            stage,
            status=new_status,
            evaluation=verdict,
            manifest=manifest,
        )
        self._update_stage_in_session(session, stage_idx, updated_stage)
        return verdict

    def advance_to_next_stage(self, session_id: str) -> TriRoleSessionState:
        """Advance session pointer to the next stage if current stage is accepted."""
        session = self._require_session(session_id)
        curr_idx = session.current_stage_index

        if curr_idx >= len(session.stages):
            msg = "Session already completed all stages."
            raise TriRolePipelineError(msg)

        curr_stage = session.stages[curr_idx]
        if curr_stage.status != StageStatus.ACCEPTED:
            msg = f"Current stage '{curr_stage.stage_id}' is not ACCEPTED (status: {curr_stage.status})."
            raise TriRolePipelineError(msg)

        next_idx = curr_idx + 1
        is_completed = next_idx >= len(session.stages)
        now = datetime.now(tz=UTC)

        updated_session = dataclasses.replace(
            session,
            current_stage_index=next_idx,
            is_completed=is_completed,
            updated_at=now,
        )
        self._sessions[session_id] = updated_session
        return updated_session

    def export_handoff_manifest(
        self,
        session_id: str,
        stage_id: str | None = None,
    ) -> ArtifactManifest:
        """Export cumulative or specific stage artifact manifest for cross-session handoff."""
        session = self._require_session(session_id)
        if stage_id is not None:
            _, stage = self._find_stage(session, stage_id)
            if stage.manifest is None:
                msg = f"Stage '{stage_id}' does not have an accepted artifact manifest."
                raise TriRolePipelineError(msg)
            return stage.manifest

        # Cumulative manifest across all accepted stages
        all_files: list[str] = []
        all_passed: list[str] = []
        all_constraints: list[str] = []

        last_accepted_idx = -1
        for idx, stage in enumerate(session.stages):
            if stage.manifest is not None:
                last_accepted_idx = idx
                for f in stage.manifest.produced_files:
                    if f not in all_files:
                        all_files.append(f)
                all_passed.extend(stage.manifest.passed_assertions)
                all_constraints.extend(stage.manifest.key_constraints)

        if last_accepted_idx == -1:
            msg = f"Session '{session_id}' has no accepted stages to export."
            raise TriRolePipelineError(msg)

        return ArtifactManifest(
            manifest_id=f"manifest_cumulative_{session_id}_{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            stage_index=last_accepted_idx,
            produced_files=all_files,
            passed_assertions=all_passed,
            key_constraints=all_constraints,
            pending_todos=[
                s.stage_name for s in session.stages if s.status != StageStatus.ACCEPTED
            ],
            created_at=datetime.now(tz=UTC),
        )

    def restore_session_from_manifest(
        self,
        manifest: ArtifactManifest,
        new_session_id: str,
        task_description: str,
        subsequent_stage_names: list[str],
    ) -> TriRoleSessionState:
        """Hydrate a brand-new session from an existing manifest with zero context loss."""
        if not new_session_id:
            msg = "New session ID cannot be empty."
            raise TriRolePipelineError(msg)
        if not subsequent_stage_names:
            msg = "Subsequent stage names must be provided to continue execution."
            raise TriRolePipelineError(msg)

        now = datetime.now(tz=UTC)
        # Prepend a synthesized handoff stage reflecting imported manifest
        imported_stage = TriRolePipelineStage(
            stage_id=f"{new_session_id}_imported_stage_0",
            stage_name="Prior Session Handoff Baseline",
            status=StageStatus.ACCEPTED,
            planner_output=f"Imported from session '{manifest.session_id}' stage {manifest.stage_index}",
            criteria=[],
            generator_output="Baseline artifacts restored from handoff manifest.",
            produced_files=list(manifest.produced_files),
            evaluation=EvaluationVerdict(
                is_accepted=True,
                score=1.0,
                evaluator_notes="Restored from previously verified artifact manifest.",
                criteria_results={},
                evaluated_at=now,
            ),
            manifest=manifest,
        )

        subsequent_stages = [
            TriRolePipelineStage(
                stage_id=f"{new_session_id}_stage_{idx + 1}",
                stage_name=name,
                status=StageStatus.PLANNED,
            )
            for idx, name in enumerate(subsequent_stage_names)
        ]

        all_stages = [imported_stage, *subsequent_stages]
        state = TriRoleSessionState(
            session_id=new_session_id,
            task_description=task_description,
            stages=all_stages,
            current_stage_index=1,  # pointing to first subsequent stage
            is_completed=False,
            created_at=now,
            updated_at=now,
        )
        self._sessions[new_session_id] = state
        return state

    def _require_session(self, session_id: str) -> TriRoleSessionState:
        session = self._sessions.get(session_id)
        if session is None:
            msg = f"Tri-role session '{session_id}' not found."
            raise TriRolePipelineError(msg)
        return session

    def _find_stage(
        self, session: TriRoleSessionState, stage_id: str
    ) -> tuple[int, TriRolePipelineStage]:
        for idx, stage in enumerate(session.stages):
            if stage.stage_id == stage_id:
                return idx, stage
        msg = f"Stage '{stage_id}' not found in session '{session.session_id}'."
        raise TriRolePipelineError(msg)

    def _update_stage_in_session(
        self,
        session: TriRoleSessionState,
        stage_idx: int,
        updated_stage: TriRolePipelineStage,
    ) -> None:
        stages = list(session.stages)
        stages[stage_idx] = updated_stage
        now = datetime.now(tz=UTC)
        self._sessions[session.session_id] = dataclasses.replace(
            session,
            stages=stages,
            updated_at=now,
        )

"""Deterministic Agent & Team Creation Pipeline with Transactional Rollback.

[INPUT]
- __future__
- time
- uuid
- safety_envelope
- types

[OUTPUT]
- CreationPipelineError
- VerifiedCreationPipeline

[POS]
Deterministic Agent & Team Creation Pipeline with Transactional Rollback.

"""

from __future__ import annotations

import time
import uuid

from .safety_envelope import (
    BuilderSafetyEnvelope,
    BuilderSafetyViolationError,
)
from .types import (
    BotProfileSpec,
    BuilderAuthority,
    CreationVerificationResult,
    OverlapVerdictEnum,
    PipelineExecutionState,
    PipelineStageEnum,
    ReadinessSeverityEnum,
    RollbackRecord,
    TeamCompositionSpec,
    VerificationFinding,
)


class CreationPipelineError(Exception):
    """Raised when a fatal pipeline error occurs requiring rollback."""


class VerifiedCreationPipeline:
    """Deterministic pipeline orchestrating multi-stage agent and team creation

    with zero-model readiness dry-run verification and fail-closed transactional rollback.
    """

    def __init__(
        self,
        builder: BuilderAuthority,
        available_models: set[str] | None = None,
        available_tools: set[str] | None = None,
        available_skills: set[str] | None = None,
        agent_store: dict[str, BotProfileSpec] | None = None,
        cron_store: dict[str, str] | None = None,
    ) -> None:
        self.builder = builder
        self.available_models = available_models or {"default-model", "gpt-5", "claude-3-7-sonnet", "deepseek-r1"}
        self.available_tools = available_tools or {"bash_exec", "file_read", "file_write", "web_search", "git_status"}
        self.available_skills = available_skills or {"code_review", "data_analysis", "ast_lint"}
        self.agent_store = agent_store if agent_store is not None else {}
        self.cron_store = cron_store if cron_store is not None else {}

    def create_single_agent(
        self,
        spec: BotProfileSpec,
        is_sandbox: bool = False,
        allow_overlap: bool = False,
    ) -> PipelineExecutionState:
        """Execute the deterministic creation pipeline for an individual agent."""
        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
        state = PipelineExecutionState(
            pipeline_id=pipeline_id,
            target_name=spec.name,
            current_stage=PipelineStageEnum.PRECHECK,
            is_team=False,
        )

        mutations_agents: list[str] = []
        mutations_crons: list[str] = []

        try:
            # Stage 1: Pre-check (model readiness, catalog existence, safety envelope)
            self._execute_precheck(spec, is_sandbox)
            state.current_stage = PipelineStageEnum.NAME_OVERLAP_GUARD

            # Stage 2: Name uniqueness & duty overlap guard
            self._execute_name_overlap_guard(spec, allow_overlap)
            state.current_stage = PipelineStageEnum.PROFILE_DESIGN

            # Stage 3: Profile design & sanitization
            sanitized_spec = self._execute_profile_design(spec)
            state.current_stage = PipelineStageEnum.PERSONA_MEMORY

            # Stage 4: Persist persona & memory
            self.agent_store[sanitized_spec.name] = sanitized_spec
            mutations_agents.append(sanitized_spec.name)
            state.created_agents.append(sanitized_spec.name)
            state.current_stage = PipelineStageEnum.ROUTINE_BIND

            # Stage 5: Bind cron routines
            for routine in sanitized_spec.cron_routines:
                cron_id = f"cron-{sanitized_spec.name}-{uuid.uuid4().hex[:6]}"
                self.cron_store[cron_id] = routine
                mutations_crons.append(cron_id)
            state.current_stage = PipelineStageEnum.POST_VERIFICATION

            # Stage 6: Post-creation verification
            verification = self._verify_agent_readiness(sanitized_spec)
            state.verification = verification

            if verification.severity == ReadinessSeverityEnum.BLOCKED:
                raise CreationPipelineError(
                    f"Readiness check failed with BLOCKED severity: {[f.message for f in verification.findings if f.severity == ReadinessSeverityEnum.BLOCKED]}"
                )

            # Successfully completed (either PASS or WARNING with next_actions)
            state.current_stage = PipelineStageEnum.COMPLETED
            state.completed_at = time.time()
            return state

        except BuilderSafetyViolationError:
            raise
        except Exception as exc:
            # Transactional Rollback
            rollback_record = self._rollback_mutations(
                target_name=spec.name,
                agents=mutations_agents,
                crons=mutations_crons,
                reason=str(exc),
            )
            state.rollback = rollback_record
            state.current_stage = PipelineStageEnum.ROLLED_BACK
            state.error = str(exc)
            state.completed_at = time.time()
            return state

    def create_team(
        self,
        team_spec: TeamCompositionSpec,
        is_sandbox: bool = False,
        allow_overlap: bool = False,
    ) -> PipelineExecutionState:
        """Atomically create a team (lead + specialists); rolls back ALL if any fails."""
        pipeline_id = f"team-pipe-{uuid.uuid4().hex[:8]}"
        state = PipelineExecutionState(
            pipeline_id=pipeline_id,
            target_name=team_spec.team_name,
            current_stage=PipelineStageEnum.PRECHECK,
            is_team=True,
        )

        all_mutations_agents: list[str] = []
        all_mutations_crons: list[str] = []

        try:
            # Team safety check
            BuilderSafetyEnvelope.validate_team_safety(self.builder, team_spec, is_sandbox)

            members = [team_spec.lead, *team_spec.specialists]
            for member in members:
                single_state = self.create_single_agent(
                    spec=member,
                    is_sandbox=is_sandbox,
                    allow_overlap=allow_overlap,
                )

                if single_state.current_stage != PipelineStageEnum.COMPLETED:
                    # Rollback triggered in single agent -> rollback entire team!
                    raise CreationPipelineError(
                        f"Team member '{member.name}' failed creation: {single_state.error}"
                    )

                all_mutations_agents.extend(single_state.created_agents)
                state.created_agents.extend(single_state.created_agents)

            state.current_stage = PipelineStageEnum.COMPLETED
            state.completed_at = time.time()
            state.verification = CreationVerificationResult(
                passed=True,
                severity=ReadinessSeverityEnum.PASS,
                findings=[
                    VerificationFinding(
                        code="TEAM_READY",
                        severity=ReadinessSeverityEnum.PASS,
                        message=f"Team '{team_spec.team_name}' successfully provisioned with {len(members)} agents.",
                    )
                ],
                observed_state={"team_members": state.created_agents},
            )
            return state

        except BuilderSafetyViolationError:
            raise
        except Exception as exc:
            # Roll back all team agents that were created so far
            rollback_record = self._rollback_mutations(
                target_name=team_spec.team_name,
                agents=all_mutations_agents,
                crons=all_mutations_crons,
                reason=str(exc),
            )
            state.rollback = rollback_record
            state.current_stage = PipelineStageEnum.ROLLED_BACK
            state.error = str(exc)
            state.completed_at = time.time()
            return state

    def _execute_precheck(self, spec: BotProfileSpec, is_sandbox: bool) -> None:
        """Validate model readiness, tool catalog existence, and safety envelope."""
        # Validate builder authority and anti-recursion
        BuilderSafetyEnvelope.validate_profile_safety(self.builder, spec, is_sandbox)

        # Check model existence
        if spec.model not in self.available_models:
            raise CreationPipelineError(
                f"Model '{spec.model}' is not configured or ready. Configured models: {sorted(self.available_models)}"
            )

        # Check tool existence
        for t in spec.tools:
            if t not in self.available_tools:
                raise CreationPipelineError(
                    f"Requested tool '{t}' is not available in system catalog."
                )

        # Check skill existence
        for s in spec.skills:
            if s not in self.available_skills:
                raise CreationPipelineError(
                    f"Requested skill '{s}' is not installed in system catalog."
                )

    def _execute_name_overlap_guard(self, spec: BotProfileSpec, allow_overlap: bool) -> None:
        """Verify name uniqueness and duty overlap against existing agents."""
        existing = list(self.agent_store.values())
        verdict, conflict_name, rec = BuilderSafetyEnvelope.detect_name_and_duty_overlap(
            candidate_name=spec.name,
            candidate_purpose=spec.description,
            existing_agents=existing,
        )

        if verdict == OverlapVerdictEnum.DUPLICATE_NAME:
            raise CreationPipelineError(f"Duplicate agent name: {rec}")

        if verdict == OverlapVerdictEnum.OVERLAPPING_DUTY and not allow_overlap:
            raise CreationPipelineError(f"Duty overlap detected with '{conflict_name}': {rec}")

    def _execute_profile_design(self, spec: BotProfileSpec) -> BotProfileSpec:
        """Sanitize cloned system prompts and format profile."""
        norm_name = BuilderSafetyEnvelope.normalize_name(spec.name)
        sanitized_prompt = BuilderSafetyEnvelope.sanitize_clone_prompt(
            original_name=spec.display_name,
            new_name=norm_name,
            system_prompt=spec.system_prompt,
        )
        return BotProfileSpec(
            name=norm_name,
            display_name=spec.display_name or norm_name,
            description=spec.description,
            system_prompt=sanitized_prompt,
            model=spec.model,
            tools=list(spec.tools),
            skills=list(spec.skills),
            mcp_servers=list(spec.mcp_servers),
            cron_routines=list(spec.cron_routines),
            role_type=spec.role_type,
        )

    def _verify_agent_readiness(self, spec: BotProfileSpec) -> CreationVerificationResult:
        """Simulate zero-model readiness dry run checking."""
        findings: list[VerificationFinding] = []
        severity = ReadinessSeverityEnum.PASS

        # Check if agent has tools
        if not spec.tools and not spec.skills:
            findings.append(
                VerificationFinding(
                    code="NO_CAPABILITIES",
                    severity=ReadinessSeverityEnum.WARNING,
                    message="Agent has no active tools or skills configured.",
                    next_action="Consider binding skills or tools to make agent actionable.",
                )
            )
            severity = ReadinessSeverityEnum.WARNING

        # Check if description is too short
        if len(spec.description.strip()) < 10:
            findings.append(
                VerificationFinding(
                    code="VAGUE_DESCRIPTION",
                    severity=ReadinessSeverityEnum.WARNING,
                    message="Agent description is very brief (<10 chars).",
                    next_action="Add detailed duty description for accurate delegation routing.",
                )
            )
            if severity != ReadinessSeverityEnum.BLOCKED:
                severity = ReadinessSeverityEnum.WARNING

        observed_state = {
            "name": spec.name,
            "status": "ready",
            "model_ready": True,
            "tools_bound": len(spec.tools),
            "skills_bound": len(spec.skills),
            "routines_bound": len(spec.cron_routines),
        }

        return CreationVerificationResult(
            passed=(severity != ReadinessSeverityEnum.BLOCKED),
            severity=severity,
            findings=findings,
            observed_state=observed_state,
        )

    def _rollback_mutations(
        self,
        target_name: str,
        agents: list[str],
        crons: list[str],
        reason: str,
    ) -> RollbackRecord:
        """Atomic rollback: revert all created agents and cron routines."""
        reverted_agents: list[str] = []
        reverted_crons: list[str] = []

        for cron_id in crons:
            if cron_id in self.cron_store:
                self.cron_store.pop(cron_id, None)
                reverted_crons.append(cron_id)

        for agent_name in agents:
            if agent_name in self.agent_store:
                self.agent_store.pop(agent_name, None)
                reverted_agents.append(agent_name)

        return RollbackRecord(
            target_name=target_name,
            reason=reason,
            reverted_agents=reverted_agents,
            reverted_crons=reverted_crons,
            timestamp=time.time(),
        )

from __future__ import annotations

import datetime
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.skill_state_patch_governor import (
    JsonMergePatchGovernor,
)
from myrm_agent_harness.runtime.context.skill_state_types import (
    AuditLogEventRecord,
    ConstantPromptTuple,
    PrebuiltStateSchemaKind,
    RetroactiveProbeQuery,
    RetroactiveProbeResult,
    clone_state,
    get_default_schema_state,
)


class SkillStateConstantPromptEngine:
    """Constant prompt engine maintaining explicit state table instead of growing history.

    Implements P + Sigma_t + O_t constant prompt tuple with O(1) step complexity,
    dual-track audit logging, and retroactive observation retrieval probe.
    """

    def __init__(
        self,
        spec_prompt: str,
        initial_state: dict[str, object] | None = None,
        schema_kind: PrebuiltStateSchemaKind | None = None,
        governor: JsonMergePatchGovernor | None = None,
        max_observation_chars: int = 4000,
    ) -> None:
        self._spec_prompt = spec_prompt.strip()
        self._schema_kind = schema_kind
        if initial_state is not None:
            self._current_state = clone_state(initial_state)
        elif schema_kind is not None:
            self._current_state = get_default_schema_state(schema_kind)
        else:
            self._current_state = {}

        self._governor = governor or JsonMergePatchGovernor(allowed_schema=schema_kind)
        self._latest_observation: str | None = None
        self._step_counter: int = 0
        self._audit_log: list[AuditLogEventRecord] = []
        self._max_observation_chars = max_observation_chars

    @property
    def current_state(self) -> dict[str, object]:
        return clone_state(self._current_state)

    @property
    def step_counter(self) -> int:
        return self._step_counter

    @property
    def audit_log(self) -> Sequence[AuditLogEventRecord]:
        return list(self._audit_log)

    def get_constant_prompt(self) -> ConstantPromptTuple:
        """Return the current constant prompt tuple (P + Sigma_t + O_t)."""
        return ConstantPromptTuple(
            spec_prompt=self._spec_prompt,
            state_table=clone_state(self._current_state),
            latest_observation=self._latest_observation,
        )

    def step(
        self,
        action_name: str,
        observation_raw: str,
        patch_raw: str | dict[str, object],
        rationale: str | None = None,
    ) -> tuple[ConstantPromptTuple, bool, str | None]:
        """Execute one step: apply patch to state table, update latest observation, archive audit log."""
        new_state, success, err = self._governor.safe_atomic_apply(
            current_state=self._current_state,
            patch_raw=patch_raw,
            schema_kind=self._schema_kind,
        )
        if not success:
            return self.get_constant_prompt(), False, err

        sanitized_patch = self._governor.sanitize_patch_input(patch_raw)
        self._step_counter += 1
        self._current_state = new_state

        # Forward-facing execution track retains only latest observation (truncated if exceeding limit)
        clean_obs = observation_raw.strip()
        if len(clean_obs) > self._max_observation_chars:
            head = clean_obs[: self._max_observation_chars // 2]
            tail = clean_obs[-self._max_observation_chars // 2 :]
            self._latest_observation = f"{head}\n...[telemetry truncated for execution track]...\n{tail}"
        else:
            self._latest_observation = clean_obs

        # Background audit track retains raw, immutable, unclipped event log
        record = AuditLogEventRecord(
            step_index=self._step_counter,
            timestamp_iso=datetime.datetime.now(datetime.UTC).isoformat(),
            action=action_name,
            observation_raw=observation_raw,
            state_snapshot=clone_state(self._current_state),
            patch_applied=sanitized_patch,
            rationale=rationale,
        )
        self._audit_log.append(record)

        return self.get_constant_prompt(), True, None

    def force_environment_mutation(
        self,
        mutation_patch: dict[str, object],
        mutation_reason: str = "environment_mutation",
    ) -> ConstantPromptTuple:
        """In-place 0-step self-healing when environment state changes externally."""
        updated_state, success, _ = self._governor.safe_atomic_apply(
            current_state=self._current_state,
            patch_raw=mutation_patch,
            schema_kind=self._schema_kind,
        )
        if success:
            self._current_state = updated_state
            self._latest_observation = f"[Environment Mutation Detected]: {mutation_reason}"
        return self.get_constant_prompt()

    def probe_audit_log(self, query: RetroactiveProbeQuery) -> RetroactiveProbeResult:
        """Retrieve omitted historical details from background audit log via probe."""
        matched: list[AuditLogEventRecord] = []
        kw = query.keyword.lower().strip()

        for rec in self._audit_log:
            if query.step_index_min is not None and rec.step_index < query.step_index_min:
                continue
            if query.step_index_max is not None and rec.step_index > query.step_index_max:
                continue
            if kw in rec.action.lower() or kw in rec.observation_raw.lower():
                matched.append(rec)

        return RetroactiveProbeResult(matched_records=matched)

    def reconcile_retroactive_observation(
        self,
        patch_to_state: dict[str, object],
    ) -> ConstantPromptTuple:
        """Incorporate retrieved historical insights back into current state table."""
        new_state, success, _ = self._governor.safe_atomic_apply(
            current_state=self._current_state,
            patch_raw=patch_to_state,
            schema_kind=self._schema_kind,
        )
        if success:
            self._current_state = new_state
        return self.get_constant_prompt()

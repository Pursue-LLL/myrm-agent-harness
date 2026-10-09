"""Unified facade for memory skill triad and physical scope isolation.

[POS]
Entrypoint orchestrating scope physical isolation, provider visible degradation,
machine CLI envelopes, and repository integration pipeline verification.

[INPUT]
- pathlib.Path
- myrm_agent_harness.toolkits.memory.skill_triad.cli_envelope.MachineEnvelopeFormatter
- myrm_agent_harness.toolkits.memory.skill_triad.degradation.DegradedStateObserver
- myrm_agent_harness.toolkits.memory.skill_triad.models.*
- myrm_agent_harness.toolkits.memory.skill_triad.pipeline.IntegrationPipelineValidator
- myrm_agent_harness.toolkits.memory.skill_triad.scope_partition.ScopePhysicalPartitionEngine

[OUTPUT]
- MemorySkillTriadFacade
- get_memory_skill_triad_facade
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.memory.skill_triad.cli_envelope import (
    MachineEnvelopeFormatter,
)
from myrm_agent_harness.toolkits.memory.skill_triad.degradation import (
    DegradedStateObserver,
)
from myrm_agent_harness.toolkits.memory.skill_triad.models import (
    DegradedStateReport,
    IntegrationSeams,
    MachineCliEnvelope,
    ScopeCoordinates,
    ScopePartitionInfo,
    SurveyFinding,
)
from myrm_agent_harness.toolkits.memory.skill_triad.pipeline import (
    IntegrationPipelineValidator,
)
from myrm_agent_harness.toolkits.memory.skill_triad.scope_partition import (
    ScopePhysicalPartitionEngine,
)


class MemorySkillTriadFacade:
    """Unified coordinator for memory skill triad and physical scope isolation."""

    def __init__(
        self,
        base_storage_dir: str | Path | None = None,
        partition_engine: ScopePhysicalPartitionEngine | None = None,
        degradation_observer: DegradedStateObserver | None = None,
        pipeline_validator: IntegrationPipelineValidator | None = None,
    ) -> None:
        self._partition_engine: ScopePhysicalPartitionEngine = (
            partition_engine or ScopePhysicalPartitionEngine(base_storage_dir)
        )
        self._degradation_observer: DegradedStateObserver = (
            degradation_observer or DegradedStateObserver()
        )
        self._pipeline_validator: IntegrationPipelineValidator = (
            pipeline_validator or IntegrationPipelineValidator()
        )

    def resolve_scope(
        self,
        coordinates: ScopeCoordinates,
        *,
        auto_create_dir: bool = True,
    ) -> ScopePartitionInfo:
        """Derives physical directory and dedicated SQLite path for scope coordinates."""
        return self._partition_engine.resolve_partition(
            coordinates, auto_create_dir=auto_create_dir
        )

    def delete_scope(self, coordinates: ScopeCoordinates) -> bool:
        """Atomically removes the physical directory for a specific scope."""
        return self._partition_engine.delete_partition(coordinates)

    def list_active_scopes(self) -> list[str]:
        """Lists active namespace hashes stored under the scopes directory."""
        return self._partition_engine.list_active_partitions()

    def assess_providers(
        self,
        configured_providers: dict[str, str],
        *,
        strict_mode: bool = False,
    ) -> DegradedStateReport:
        """Inspects provider configuration and returns visible degradation status."""
        return self._degradation_observer.assess_providers(
            configured_providers, strict_mode=strict_mode
        )

    @staticmethod
    def wrap_cli_success(
        command: str,
        start_time_s: float,
        scope: ScopeCoordinates,
        payload: dict[str, str],
        *,
        agent_mode: bool = True,
    ) -> MachineCliEnvelope:
        """Wraps successful execution into MachineCliEnvelope."""
        return MachineEnvelopeFormatter.wrap_success(
            command, start_time_s, scope, payload, agent_mode=agent_mode
        )

    @staticmethod
    def wrap_cli_error(
        command: str,
        start_time_s: float,
        scope: ScopeCoordinates,
        error_type: str,
        error_message: str,
        *,
        agent_mode: bool = True,
    ) -> MachineCliEnvelope:
        """Wraps failure into MachineCliEnvelope with predictable exit code."""
        return MachineEnvelopeFormatter.wrap_error(
            command, start_time_s, scope, error_type, error_message, agent_mode=agent_mode
        )

    def validate_survey(self, finding: SurveyFinding) -> tuple[bool, list[str]]:
        """Validates pre-integration repository survey findings."""
        return self._pipeline_validator.validate_survey(finding)

    def verify_seams(self, seams: IntegrationSeams) -> tuple[bool, str]:
        """Verifies read and write seams are budgeted and configured."""
        return self._pipeline_validator.verify_seams(seams)

    def execute_roundtrip_probe(
        self,
        probe_dir: Path | str,
        stored_preference: str,
        query_text: str,
    ) -> bool:
        """Executes lightweight roundtrip probe in temporary directory."""
        return self._pipeline_validator.execute_roundtrip_probe(
            probe_dir, stored_preference, query_text
        )


_FACADE_INSTANCE: MemorySkillTriadFacade | None = None


def get_memory_skill_triad_facade() -> MemorySkillTriadFacade:
    """Returns singleton instance of MemorySkillTriadFacade."""
    global _FACADE_INSTANCE
    if _FACADE_INSTANCE is None:
        _FACADE_INSTANCE = MemorySkillTriadFacade()
    return _FACADE_INSTANCE

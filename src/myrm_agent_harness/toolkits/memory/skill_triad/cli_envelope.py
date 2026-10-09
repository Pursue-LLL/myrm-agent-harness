"""Standardized machine CLI envelope formatter for agent tool loops.

[POS]
Formats memory operations for command-line invocation and automation scripts.
Provides structured JSON envelopes on stdout for both successes and errors,
maps domain errors to predictable exit codes, and guarantees auto-confirmed
execution in agent mode to prevent terminal input deadlocks.

[INPUT]
- time.perf_counter
- myrm_agent_harness.toolkits.memory.skill_triad.models.MachineCliEnvelope
- myrm_agent_harness.toolkits.memory.skill_triad.models.ScopeCoordinates

[OUTPUT]
- MachineEnvelopeFormatter
"""

from __future__ import annotations

import time
from typing import ClassVar

from myrm_agent_harness.toolkits.memory.skill_triad.models import (
    MachineCliEnvelope,
    ScopeCoordinates,
)


class MachineEnvelopeFormatter:
    """Formats CLI memory outputs into structured machine-readable envelopes."""

    ERROR_CODES: ClassVar[dict[str, tuple[str, int]]] = {
        "NOT_FOUND": ("MEM_ERR_NOT_FOUND_001", 1),
        "VALIDATION_FAILED": ("MEM_ERR_VALIDATION_007", 2),
        "PROVIDER_UNAVAILABLE": ("MEM_ERR_PROVIDER_DOWN_053", 3),
        "SCOPE_EMPTY": ("MEM_ERR_SCOPE_REQUIRED_089", 4),
        "LOCK_CONTENTION": ("MEM_ERR_CONCURRENCY_102", 5),
        "INTERNAL": ("MEM_ERR_INTERNAL_500", 10),
    }

    @staticmethod
    def wrap_success(
        command: str,
        start_time_s: float,
        scope: ScopeCoordinates,
        payload: dict[str, str],
        *,
        agent_mode: bool = True,
    ) -> MachineCliEnvelope:
        """Wraps successful execution into MachineCliEnvelope.

        In agent mode, confirmation prompts are automatically assumed (equivalent
        to '--yes') so unattended tool loops never block on terminal prompts.
        """
        duration_ms = max(0, int((time.perf_counter() - start_time_s) * 1000))
        return MachineCliEnvelope(
            status="success",
            command=command,
            duration_ms=duration_ms,
            scope=scope.as_dict(),
            payload=payload,
            error_code="",
            error_message="",
            exit_code=0,
            auto_confirmed=agent_mode,
        )

    @classmethod
    def wrap_error(
        cls,
        command: str,
        start_time_s: float,
        scope: ScopeCoordinates,
        error_type: str,
        error_message: str,
        *,
        agent_mode: bool = True,
    ) -> MachineCliEnvelope:
        """Wraps execution failure into standardized error envelope.

        Errors are routed to stdout as JSON with an explicit non-zero exit code
        so calling agents never have to guess failure status or parse ad-hoc tracebacks.
        """
        duration_ms = max(0, int((time.perf_counter() - start_time_s) * 1000))
        err_code, exit_code = cls.ERROR_CODES.get(
            error_type.upper(), ("MEM_ERR_GENERIC_999", 1)
        )
        return MachineCliEnvelope(
            status="error",
            command=command,
            duration_ms=duration_ms,
            scope=scope.as_dict(),
            payload={},
            error_code=err_code,
            error_message=error_message,
            exit_code=exit_code,
            auto_confirmed=agent_mode,
        )

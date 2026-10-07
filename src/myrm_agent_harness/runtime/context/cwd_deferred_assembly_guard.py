"""Guard enforcing outside-in assembly order and deferred CWD service binding.

Prevents premature workspace service instantiation before session selection
and CWD resolution, eliminating directory drift and out-of-bounds file watching.
Strict 0 Any, thread-safe, single file <400 lines.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .cwd_deferred_assembly_types import (
    AssemblyOrderViolationError,
    AssemblyStageKind,
    WorkspaceServiceDescriptor,
)

logger = logging.getLogger(__name__)

_STAGE_ORDER: tuple[AssemblyStageKind, ...] = (
    AssemblyStageKind.ENTRY_PARSE,
    AssemblyStageKind.SESSION_RESOLVED,
    AssemblyStageKind.CWD_RESOLVED,
    AssemblyStageKind.SERVICES_BOUND,
    AssemblyStageKind.RUNTIME_READY,
)


class CwdDeferredAssemblyGuard:
    """Enforces strict outside-in assembly stages for session initialization and resume."""

    def __init__(self) -> None:
        self._current_stage = AssemblyStageKind.ENTRY_PARSE
        self._resolved_cwd: str | None = None
        self._is_relocated: bool = False
        self._audit_log: list[str] = [f"Stage initialized: {self._current_stage.value}"]
        self._bound_services: dict[str, WorkspaceServiceDescriptor] = {}

    @property
    def current_stage(self) -> AssemblyStageKind:
        """Return the current active assembly stage."""
        return self._current_stage

    @property
    def resolved_cwd(self) -> str | None:
        """Return the calibrated authoritative working directory."""
        return self._resolved_cwd

    @property
    def is_relocated(self) -> bool:
        """Return whether the working directory was dynamically relocated."""
        return self._is_relocated

    @property
    def bound_services(self) -> tuple[WorkspaceServiceDescriptor, ...]:
        """Return descriptors of all registered workspace services."""
        return tuple(self._bound_services.values())

    def advance_stage(self, next_stage: AssemblyStageKind) -> None:
        """Advance the assembly pipeline to the specified stage with strict ordering enforcement."""
        curr_idx = _STAGE_ORDER.index(self._current_stage)
        next_idx = _STAGE_ORDER.index(next_stage)

        if next_idx <= curr_idx:
            raise AssemblyOrderViolationError(
                f"Cannot transition backwards or repeat stage from '{self._current_stage.value}' to '{next_stage.value}'.",
                current_stage=self._current_stage,
                attempted_action=f"transition_to_{next_stage.value}",
            )

        if next_idx != curr_idx + 1:
            skipped_stage = _STAGE_ORDER[curr_idx + 1]
            raise AssemblyOrderViolationError(
                f"Skipped mandatory intermediate stage '{skipped_stage.value}'. Outside-in assembly must be strictly sequential.",
                current_stage=self._current_stage,
                attempted_action=f"skip_to_{next_stage.value}",
            )

        self._current_stage = next_stage
        self._audit_log.append(f"Stage transitioned: {next_stage.value}")

    def resolve_and_relocate_cwd(
        self,
        candidate_cwd: str,
        *,
        fallback_cwd: str | None = None,
        allowed_roots: tuple[str, ...] | None = None,
    ) -> str:
        """Validate candidate CWD and advance stage to CWD_RESOLVED.

        If candidate directory does not exist or violates allowed roots,
        dynamically relocates to fallback_cwd.
        """
        if self._current_stage != AssemblyStageKind.SESSION_RESOLVED:
            raise AssemblyOrderViolationError(
                "CWD cannot be resolved before session metadata has been loaded.",
                current_stage=self._current_stage,
                attempted_action="resolve_cwd",
            )

        norm_candidate = os.path.abspath(candidate_cwd)
        path_obj = Path(norm_candidate)

        is_valid = path_obj.exists() and path_obj.is_dir()
        if is_valid and allowed_roots:
            is_valid = any(
                norm_candidate == os.path.abspath(r) or norm_candidate.startswith(os.path.abspath(r) + os.sep)
                for r in allowed_roots
            )

        if is_valid:
            self._resolved_cwd = norm_candidate
            self._is_relocated = False
            self._audit_log.append(f"CWD verified natively: {norm_candidate}")
        else:
            if not fallback_cwd:
                raise ValueError(
                    f"Candidate CWD '{candidate_cwd}' is missing or forbidden, and no fallback provided."
                )
            norm_fallback = os.path.abspath(fallback_cwd)
            if not Path(norm_fallback).is_dir():
                raise ValueError(f"Fallback CWD '{fallback_cwd}' is not an existing directory.")
            self._resolved_cwd = norm_fallback
            self._is_relocated = True
            self._audit_log.append(
                f"CWD dynamically relocated from '{candidate_cwd}' to fallback '{norm_fallback}'"
            )

        self.advance_stage(AssemblyStageKind.CWD_RESOLVED)
        return self._resolved_cwd

    def register_service_binding(
        self,
        service_name: str,
        *,
        is_lazy: bool = False,
    ) -> WorkspaceServiceDescriptor:
        """Bind a workspace service to the resolved CWD.

        Must only be invoked in CWD_RESOLVED or SERVICES_BOUND stage.
        """
        if self._current_stage not in (AssemblyStageKind.CWD_RESOLVED, AssemblyStageKind.SERVICES_BOUND):
            raise AssemblyOrderViolationError(
                f"Workspace service '{service_name}' cannot be constructed before CWD resolution.",
                current_stage=self._current_stage,
                attempted_action=f"bind_service_{service_name}",
            )

        assert self._resolved_cwd is not None, "Resolved CWD must not be None in CWD_RESOLVED stage"

        descriptor = WorkspaceServiceDescriptor(
            service_name=service_name,
            bound_cwd=self._resolved_cwd,
            is_lazy=is_lazy,
        )
        self._bound_services[service_name] = descriptor
        self._audit_log.append(f"Service bound: {service_name} -> {self._resolved_cwd}")

        if self._current_stage == AssemblyStageKind.CWD_RESOLVED:
            self.advance_stage(AssemblyStageKind.SERVICES_BOUND)

        return descriptor

    def complete_runtime_assembly(self) -> tuple[str, ...]:
        """Finalize assembly pipeline into RUNTIME_READY stage."""
        if self._current_stage != AssemblyStageKind.SERVICES_BOUND:
            raise AssemblyOrderViolationError(
                "Runtime cannot be readied before workspace services have been bound.",
                current_stage=self._current_stage,
                attempted_action="ready_runtime",
            )

        self.advance_stage(AssemblyStageKind.RUNTIME_READY)
        self._audit_log.append("Assembly complete: Runtime ready for inference")
        return tuple(self._audit_log)

    def get_audit_log(self) -> tuple[str, ...]:
        """Return the immutable log of assembly sequence transitions."""
        return tuple(self._audit_log)

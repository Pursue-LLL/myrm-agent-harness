"""Deferred session runtime factory orchestrating outside-in assembly.

Ensures working directory (CWD) is authoritative and calibrated before
instantiating workspace-bound services (Git, Linters, FileWatchers),
eliminating directory drift during historical session resume and cross-project switching.
Strict 0 Any, thread-safe, single file <400 lines.

[INPUT]
- runtime.context.cwd_deferred_assembly_guard::CwdDeferredAssemblyGuard (POS: Guard enforcing outside-in
  assembly order and deferred CWD service binding.)
- runtime.context.cwd_deferred_assembly_types::AssemblyOrderViolationError, AssemblyStageKind,
  SessionMetadataHeader, SessionResumeVerificationResult (POS: Type contracts for CWD deferred workspace
  service binding and session resume order.)

[OUTPUT]
- AssembledRuntimeContainer: Container holding the fully initialized runtime and its bound services.
- DeferredSessionRuntimeFactory: Factory executing strict outside-in assembly order for session execution
  and resume.
- MockWorkspaceService: Mock workspace-bound service for verification and testing.

[POS]
Deferred session runtime factory orchestrating outside-in assembly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import NamedTuple

from .cwd_deferred_assembly_guard import CwdDeferredAssemblyGuard
from .cwd_deferred_assembly_types import (
    AssemblyOrderViolationError,
    AssemblyStageKind,
    SessionMetadataHeader,
    SessionResumeVerificationResult,
)

logger = logging.getLogger(__name__)


class AssembledRuntimeContainer(NamedTuple):
    """Container holding the fully initialized runtime and its bound services."""

    session_id: str
    calibrated_cwd: str
    is_relocated: bool
    services: dict[str, object]
    guard: CwdDeferredAssemblyGuard


class DeferredSessionRuntimeFactory:
    """Factory executing strict outside-in assembly order for session execution and resume."""

    def __init__(
        self,
        *,
        allowed_roots: tuple[str, ...] | None = None,
        default_fallback_cwd: str | None = None,
    ) -> None:
        self._allowed_roots = allowed_roots
        self._default_fallback = default_fallback_cwd

    def assemble_session_runtime(
        self,
        session_header: SessionMetadataHeader,
        *,
        service_factories: Mapping[str, Callable[[str], object]],
        target_cwd_override: str | None = None,
        fallback_cwd: str | None = None,
    ) -> tuple[AssembledRuntimeContainer, SessionResumeVerificationResult]:
        """Execute strict outside-in assembly order for a selected session.

        Order:
        1. ENTRY_PARSE (Implicitly verified at start)
        2. SESSION_RESOLVED (Session metadata provided and ingested)
        3. CWD_RESOLVED (CWD validated/relocated before service instantiation)
        4. SERVICES_BOUND (Services instantiated strictly against resolved CWD)
        5. RUNTIME_READY (Finalized for active inference)
        """
        guard = CwdDeferredAssemblyGuard()

        try:
            # Step 1 -> Step 2: Ingest session header
            guard.advance_stage(AssemblyStageKind.SESSION_RESOLVED)

            # Step 2 -> Step 3: Resolve and relocate CWD
            candidate_cwd = target_cwd_override or session_header.original_cwd
            effective_fallback = fallback_cwd or self._default_fallback
            resolved_cwd = guard.resolve_and_relocate_cwd(
                candidate_cwd,
                fallback_cwd=effective_fallback,
                allowed_roots=self._allowed_roots,
            )

            # Step 3 -> Step 4: Instantiate services strictly against resolved CWD
            constructed_services: dict[str, object] = {}
            for name, factory in service_factories.items():
                guard.register_service_binding(name)
                # Factory callback receives authoritative calibrated CWD
                instance = factory(resolved_cwd)
                constructed_services[name] = instance

            # Step 4 -> Step 5: Ready runtime
            audit_log = guard.complete_runtime_assembly()

            container = AssembledRuntimeContainer(
                session_id=session_header.session_id,
                calibrated_cwd=resolved_cwd,
                is_relocated=guard.is_relocated,
                services=constructed_services,
                guard=guard,
            )

            verification = SessionResumeVerificationResult(
                valid=True,
                target_session_id=session_header.session_id,
                resolved_cwd=resolved_cwd,
                is_relocated=guard.is_relocated,
                assembly_order_log=audit_log,
                bound_service_names=tuple(constructed_services.keys()),
                error=None,
            )

            return container, verification

        except (AssemblyOrderViolationError, ValueError, RuntimeError) as exc:
            logger.error("Session runtime assembly failed for %s: %s", session_header.session_id, exc)
            raise


class MockWorkspaceService:
    """Mock workspace-bound service for verification and testing."""

    def __init__(self, bound_cwd: str, service_name: str = "mock_service") -> None:
        self.bound_cwd = bound_cwd
        self.service_name = service_name

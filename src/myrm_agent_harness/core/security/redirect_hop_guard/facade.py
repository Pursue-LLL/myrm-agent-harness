"""Facade for Redirect Private Address Hop Revalidation Suite.

[INPUT]
- .types::HopDisposition, HopEvaluationResult, HopViolationAuditRecord, RedirectHopGuardConfig
- .hop_evaluator::RedirectHopEvaluator
- .route_interceptor::PageLike, RedirectHopRouteInterceptor, RouteLike
- stdlib collections, threading

[OUTPUT]
- RedirectHopGuardFacade: unified orchestration interface for hop security and audit

[POS]
Main entry point for redirect private address hop revalidation in harness.
Maintains audit record history and coordinates evaluators and interceptors.
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

import threading
from collections import deque

from myrm_agent_harness.core.security.redirect_hop_guard.hop_evaluator import (
    RedirectHopEvaluator,
)
from myrm_agent_harness.core.security.redirect_hop_guard.route_interceptor import (
    PageLike,
    RedirectHopRouteInterceptor,
    RouteLike,
)
from myrm_agent_harness.core.security.redirect_hop_guard.types import (
    HopEvaluationResult,
    HopViolationAuditRecord,
    RedirectHopGuardConfig,
)


class RedirectHopGuardFacade:
    """Unified facade managing redirect hop revalidation and violation audit history."""

    def __init__(self, config: RedirectHopGuardConfig | None = None) -> None:
        self._config = config or RedirectHopGuardConfig()
        self._evaluator = RedirectHopEvaluator(self._config)
        self._interceptor = RedirectHopRouteInterceptor(self._evaluator, self._config)
        self._violations: deque[HopViolationAuditRecord] = deque(maxlen=self._config.audit_history_max_size)
        self._lock = threading.Lock()

    @property
    def config(self) -> RedirectHopGuardConfig:
        return self._config

    @property
    def evaluator(self) -> RedirectHopEvaluator:
        return self._evaluator

    @property
    def interceptor(self) -> RedirectHopRouteInterceptor:
        return self._interceptor

    def update_config(self, config: RedirectHopGuardConfig) -> None:
        """Update configuration policy and reinitialize components."""
        with self._lock:
            self._config = config
            self._evaluator = RedirectHopEvaluator(config)
            self._interceptor = RedirectHopRouteInterceptor(self._evaluator, config)
            # Resize deque if max_size changed
            old_items = list(self._violations)
            self._violations = deque(old_items, maxlen=config.audit_history_max_size)

    def evaluate_hop(self, target_url: str, resource_type: str = "document") -> HopEvaluationResult:
        """Evaluate a target URL without mutating route or audit state."""
        return self._evaluator.evaluate_hop(target_url, resource_type=resource_type)

    async def handle_route(
        self,
        route: RouteLike,
        page: PageLike | None = None,
        initial_url: str = "",
    ) -> tuple[HopEvaluationResult, HopViolationAuditRecord | None]:
        """Inspect route and record violation if intercepted."""
        result, violation = await self._interceptor.inspect_and_handle_route(
            route=route,
            page=page,
            initial_url=initial_url,
        )
        if violation is not None:
            with self._lock:
                self._violations.append(violation)
        return result, violation

    def get_violations(self) -> list[HopViolationAuditRecord]:
        """Return a copy of recent violation audit records."""
        with self._lock:
            return list(self._violations)

    def clear_violations(self) -> None:
        """Clear the in-memory violation audit log."""
        with self._lock:
            self._violations.clear()

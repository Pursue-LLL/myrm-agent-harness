"""Playwright Route interceptor for hop-by-hop private address revalidation.

[INPUT]
- .types::HopDisposition, HopEvaluationResult, HopViolationAuditRecord, RedirectHopGuardConfig
- .hop_evaluator::RedirectHopEvaluator
- stdlib datetime, logging, typing

[OUTPUT]
- RedirectHopRouteInterceptor: handles route interception, about:blank resets, and audit recording

[POS]
Integrates with browser networking layer to abort private network hops,
reset document tabs to about:blank on illegal redirects, and record audits.
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

from myrm_agent_harness.core.security.redirect_hop_guard.hop_evaluator import (
    RedirectHopEvaluator,
)
from myrm_agent_harness.core.security.redirect_hop_guard.types import (
    HopDisposition,
    HopEvaluationResult,
    HopViolationAuditRecord,
    RedirectHopGuardConfig,
)

logger = logging.getLogger(__name__)


class RouteLike(Protocol):
    """Protocol representing Playwright Route interface."""

    @property
    def request(self) -> RequestLike: ...
    async def abort(self, error_code: str | None = None) -> None: ...
    async def continue_(self) -> None: ...


class RequestLike(Protocol):
    """Protocol representing Playwright Request interface."""

    @property
    def url(self) -> str: ...
    @property
    def resource_type(self) -> str: ...


class PageLike(Protocol):
    """Protocol representing Playwright Page interface."""

    async def goto(self, url: str) -> object: ...


class RedirectHopRouteInterceptor:
    """Intercepts browser requests and enforces hop-by-hop private network blocks."""

    def __init__(
        self,
        evaluator: RedirectHopEvaluator | None = None,
        config: RedirectHopGuardConfig | None = None,
    ) -> None:
        self._config = config or RedirectHopGuardConfig()
        self._evaluator = evaluator or RedirectHopEvaluator(self._config)

    @property
    def config(self) -> RedirectHopGuardConfig:
        return self._config

    @property
    def evaluator(self) -> RedirectHopEvaluator:
        return self._evaluator

    async def inspect_and_handle_route(
        self,
        route: RouteLike,
        page: PageLike | None = None,
        initial_url: str = "",
    ) -> tuple[HopEvaluationResult, HopViolationAuditRecord | None]:
        """Inspect the current route and perform enforcement actions.

        Args:
            route: The route object intercepting the request.
            page: Optional current active page to reset on document redirect violations.
            initial_url: The initial navigation URL for correlation.

        Returns:
            Tuple of (HopEvaluationResult, optional HopViolationAuditRecord).
        """
        request_url = route.request.url
        resource_type = route.request.resource_type

        eval_result = self._evaluator.evaluate_hop(request_url, resource_type=resource_type)
        audit_record: HopViolationAuditRecord | None = None

        if eval_result.disposition == HopDisposition.ALLOW:
            try:
                await route.continue_()
            except Exception as exc:
                logger.debug("Failed to continue route: %s", exc)
            return eval_result, None

        # Violation encountered
        timestamp = datetime.now(UTC).isoformat()
        audit_record = HopViolationAuditRecord(
            timestamp_iso=timestamp,
            initial_url=initial_url or request_url,
            hop_url=request_url,
            resource_type=resource_type,
            disposition=eval_result.disposition,
            matched_rule=eval_result.matched_rule,
            reason=eval_result.reason,
        )

        logger.warning(
            "SECURITY INTERCEPTION: Blocked private network hop [%s] -> %s (Rule: %s, Reason: %s)",
            eval_result.disposition.value,
            request_url,
            eval_result.matched_rule,
            eval_result.reason,
        )

        if eval_result.disposition == HopDisposition.ABORT_AND_RESET_DOCUMENT:
            # Document-level redirect violation: reset tab to about:blank to clear DOM/state
            if page is not None and self._config.reset_to_about_blank:
                try:
                    logger.info("Resetting tab to about:blank due to document-level private redirect")
                    await page.goto("about:blank")
                except Exception as exc:
                    logger.warning("Failed to reset tab to about:blank: %s", exc)

            try:
                await route.abort("blockedbyclient")
            except Exception as exc:
                logger.debug("Failed to abort document route: %s", exc)
        else:
            # Subresource violation
            try:
                await route.abort("blockedbyclient")
            except Exception as exc:
                logger.debug("Failed to abort subresource route: %s", exc)

        return eval_result, audit_record

"""Redirect Private Address Hop Revalidation Suite.

[INPUT]
- .types::HopDisposition, HopEvaluationResult, HopViolationAuditRecord, RedirectHopGuardConfig
- .hop_evaluator::RedirectHopEvaluator
- .route_interceptor::PageLike, RedirectHopRouteInterceptor, RouteLike
- .facade::RedirectHopGuardFacade

[OUTPUT]
All core domain models, evaluator, interceptor, and facade re-exported.

[POS]
Complete suite providing hop-by-hop private network and metadata revalidation
for browser navigations and redirect chains.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.redirect_hop_guard.facade import (
    RedirectHopGuardFacade,
)
from myrm_agent_harness.core.security.redirect_hop_guard.hop_evaluator import (
    RedirectHopEvaluator,
)
from myrm_agent_harness.core.security.redirect_hop_guard.route_interceptor import (
    PageLike,
    RedirectHopRouteInterceptor,
    RouteLike,
)
from myrm_agent_harness.core.security.redirect_hop_guard.types import (
    HopDisposition,
    HopEvaluationResult,
    HopViolationAuditRecord,
    RedirectHopGuardConfig,
)

__all__ = [
    "HopDisposition",
    "HopEvaluationResult",
    "HopViolationAuditRecord",
    "PageLike",
    "RedirectHopEvaluator",
    "RedirectHopGuardConfig",
    "RedirectHopGuardFacade",
    "RedirectHopRouteInterceptor",
    "RouteLike",
]

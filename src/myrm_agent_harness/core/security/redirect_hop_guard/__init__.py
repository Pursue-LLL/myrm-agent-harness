"""Redirect Private Address Hop Revalidation Suite.

[INPUT]
- .types::HopDisposition, HopEvaluationResult
- .hop_evaluator::RedirectHopEvaluator
- .origin_grants::PrivateOriginGrants

[OUTPUT]
Hop domain models, the evaluator and the explicit-origin grants, re-exported.

[POS]
Literal-host private network and cloud metadata classification for browser navigations, the browser
context filter and web_fetch redirect chains. Enforcement (route aborts, tab resets, request
refusal) lives with each caller; this package only judges a URL.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.redirect_hop_guard.hop_evaluator import RedirectHopEvaluator
from myrm_agent_harness.core.security.redirect_hop_guard.origin_grants import PrivateOriginGrants
from myrm_agent_harness.core.security.redirect_hop_guard.types import HopDisposition, HopEvaluationResult

__all__ = [
    "HopDisposition",
    "HopEvaluationResult",
    "PrivateOriginGrants",
    "RedirectHopEvaluator",
]

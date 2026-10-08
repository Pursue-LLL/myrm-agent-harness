"""
[POS] src/myrm_agent_harness/core/security/subdomain_ticket_gateway/subdomain_airgap_guard.py
[INPUT] logging, re, typing, .types
[OUTPUT] SubdomainAirgapGuard

Least-privilege airgap guard enforcing strict outbound isolation for sandbox subdomains.
Blocks any sandbox attempt to reverse-engineer or query the master control plane
or breach cross-instance boundaries.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import re

from .types import AirgapAccessVerdict, AirgapEvaluationResult

logger = logging.getLogger(__name__)


class SubdomainAirgapGuard:
    """Enforces subdomain airgap boundaries and prevents lateral or uplink privilege escalation."""

    _DEFAULT_FORBIDDEN_CONTROL_PLANE_PATTERNS: tuple[str, ...] = (
        r"^/api/v1/admin(/|$)",
        r"^/api/v1/organizations(/|$)",
        r"^/api/v1/global-users(/|$)",
        r"^/api/v1/billing(/|$)",
        r"^/api/v1/tenants(/|$)",
        r"^/console(/|$)",
        r"^/api/v1/clusters(/|$)",
    )

    def __init__(
        self,
        custom_forbidden_patterns: list[str] | None = None,
    ) -> None:
        patterns = list(self._DEFAULT_FORBIDDEN_CONTROL_PLANE_PATTERNS)
        if custom_forbidden_patterns:
            patterns.extend(custom_forbidden_patterns)
        self._forbidden_regex = re.compile("|".join(patterns), re.IGNORECASE)

    def evaluate_egress_request(
        self,
        current_instance_id: str,
        requested_path: str,
        target_instance_id: str | None = None,
    ) -> AirgapEvaluationResult:
        """Inspect request destination from sandbox against airgap constraints."""
        normalized_path = "/" + requested_path.lstrip("/")

        # 1. Block any attempt to communicate with master control plane management endpoints
        if self._forbidden_regex.search(normalized_path):
            msg = (
                f"Blocked sandbox attempt from instance '{current_instance_id}' "
                f"to call master control plane endpoint '{requested_path}'."
            )
            logger.error("Airgap violation: %s", msg)
            return AirgapEvaluationResult(
                is_allowed=False,
                verdict=AirgapAccessVerdict.BLOCKED_MASTER_CONTROL_PLANE_ATTEMPT,
                requested_path=requested_path,
                target_instance_id=target_instance_id or current_instance_id,
                diagnostic_reason=msg,
            )

        # 2. Block cross-instance lateral traversal attempts
        if target_instance_id and target_instance_id != current_instance_id:
            msg = (
                f"Blocked cross-instance traversal from '{current_instance_id}' "
                f"targeting instance '{target_instance_id}' at path '{requested_path}'."
            )
            logger.error("Airgap violation: %s", msg)
            return AirgapEvaluationResult(
                is_allowed=False,
                verdict=AirgapAccessVerdict.BLOCKED_CROSS_INSTANCE_ATTEMPT,
                requested_path=requested_path,
                target_instance_id=target_instance_id,
                diagnostic_reason=msg,
            )

        # 3. Allow standard local sandbox runtime execution calls
        logger.debug(
            "Airgap check passed for instance '%s' requesting '%s'.",
            current_instance_id,
            requested_path,
        )
        return AirgapEvaluationResult(
            is_allowed=True,
            verdict=AirgapAccessVerdict.ALLOWED_SANDBOX_LOCAL,
            requested_path=requested_path,
            target_instance_id=current_instance_id,
            diagnostic_reason="Request allowed within sandbox local scope.",
        )

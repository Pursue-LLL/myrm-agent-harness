"""
[POS] src/myrm_agent_harness/core/security/system_app_boundary/write_consent_gate.py
[INPUT] types
[OUTPUT] WriteConsentGate
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .types import AppAccessRequest

logger = logging.getLogger(__name__)


class WriteConsentGate:
    """Manages pending human-in-the-loop write consent requests and one-time approvals."""

    def __init__(self) -> None:
        self._pending_requests: dict[str, AppAccessRequest] = {}

    def enqueue_for_consent(self, request: AppAccessRequest) -> None:
        """Enqueue high-risk or unprompted write request pending explicit user authorization."""
        self._pending_requests[request.request_id] = request
        logger.info(
            "Write consent requested for %s on app %s (req_id=%s)",
            request.operation_type,
            request.app_type,
            request.request_id,
        )

    def grant_consent(
        self, request_id: str, approver_note: str = "Authorized by User"
    ) -> AppAccessRequest | None:
        """Grant one-time execution consent and dequeue request."""
        req = self._pending_requests.pop(request_id, None)
        if req is not None:
            logger.info("Write consent granted for req_id=%s: %s", request_id, approver_note)
        return req

    def reject_consent(
        self, request_id: str, reason: str = "Rejected by User"
    ) -> bool:
        """Reject and drop pending write request."""
        removed = self._pending_requests.pop(request_id, None)
        if removed is not None:
            logger.info("Write consent rejected for req_id=%s: %s", request_id, reason)
            return True
        return False

    def list_pending_consents(self) -> tuple[AppAccessRequest, ...]:
        """List all write requests currently awaiting user decision."""
        return tuple(self._pending_requests.values())

    def get_pending_request(self, request_id: str) -> AppAccessRequest | None:
        """Retrieve a specific pending request by ID."""
        return self._pending_requests.get(request_id)

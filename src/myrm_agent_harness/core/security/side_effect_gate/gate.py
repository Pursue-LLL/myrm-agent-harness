"""Physical interceptor and authorization gate for irreversible external actions.

[INPUT]
- Tool name, arguments, session ID, authorization token

[OUTPUT]
- PreActionEvaluationResult: Interception decision outcome
- PreActionSideEffectGate: Physical gate intercepting mutating tools before dispatch

[POS]
Harness core security gate. Prevents irreversible actions (emails, charges, config mutations)
from executing without explicit human pre-action approval.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from uuid import uuid4

from myrm_agent_harness.core.security.side_effect_gate.idempotency import (
    IdempotencyReceiptCache,
    compute_idempotency_key,
)
from myrm_agent_harness.core.security.side_effect_gate.types import (
    ActionArguments,
    ActionReceipt,
    PreActionChallenge,
    PreActionDeniedError,
    PreActionRiskLevel,
    PreActionStatus,
    SideEffectType,
)

logger = logging.getLogger(__name__)

_DEFAULT_MUTATING_EXTERNAL_TOOLS: frozenset[str] = frozenset({
    "send_email",
    "smtp_send",
    "send_mail",
    "stripe_charge",
    "process_payment",
    "purchase_order",
    "deploy_production",
    "delete_database",
    "slack_post_message",
    "webhook_post",
    "cloud_resource_delete",
})


@dataclass(frozen=True, slots=True)
class PreActionEvaluationResult:
    """Outcome of pre-action side-effect evaluation."""

    allowed: bool
    status: PreActionStatus
    idempotency_key: str
    challenge: PreActionChallenge | None = None
    cached_receipt: ActionReceipt | None = None
    auth_token: str | None = None
    reason: str = ""


class PreActionSideEffectGate:
    """Evaluates and intercepts irreversible external actions before physical execution."""

    def __init__(
        self,
        receipt_cache: IdempotencyReceiptCache | None = None,
        mutating_external_tools: set[str] | None = None,
    ) -> None:
        self._receipt_cache = receipt_cache if receipt_cache is not None else IdempotencyReceiptCache()
        self._mutating_tools: set[str] = (
            set(mutating_external_tools)
            if mutating_external_tools is not None
            else set(_DEFAULT_MUTATING_EXTERNAL_TOOLS)
        )
        self._challenges: dict[str, PreActionChallenge] = {}
        self._challenge_statuses: dict[str, PreActionStatus] = {}
        self._authorized_tokens: dict[str, str] = {}  # token -> idempotency_key
        self._lock = threading.Lock()

    @property
    def receipt_cache(self) -> IdempotencyReceiptCache:
        """Access underlying receipt cache."""
        return self._receipt_cache

    def register_mutating_tool(self, tool_name: str) -> None:
        """Register a tool name as requiring pre-action authorization."""
        with self._lock:
            self._mutating_tools.add(tool_name)

    def classify_tool(self, tool_name: str) -> SideEffectType:
        """Determine side-effect classification of given tool."""
        with self._lock:
            if tool_name in self._mutating_tools:
                return SideEffectType.MUTATING_EXTERNAL
        return SideEffectType.WORKSPACE_LOCAL

    def evaluate_action(
        self,
        session_id: str,
        tool_name: str,
        arguments: ActionArguments,
        auth_token: str | None = None,
        sequence: int = 0,
    ) -> PreActionEvaluationResult:
        """Physically evaluate whether a tool action is permitted to execute."""
        effect_type = self.classify_tool(tool_name)
        if effect_type != SideEffectType.MUTATING_EXTERNAL:
            idempotency_key = compute_idempotency_key(session_id, tool_name, arguments, sequence)
            return PreActionEvaluationResult(
                allowed=True,
                status=PreActionStatus.BYPASSED,
                idempotency_key=idempotency_key,
                reason="Tool does not possess external mutating side effects",
            )

        idempotency_key = compute_idempotency_key(session_id, tool_name, arguments, sequence)

        # 1. Check idempotency receipt cache (prevents duplicate execution on retry/crash)
        cached_receipt = self._receipt_cache.get_receipt(idempotency_key)
        if cached_receipt is not None:
            logger.info("Idempotent replay detected for key %s (tool: %s)", idempotency_key, tool_name)
            return PreActionEvaluationResult(
                allowed=True,
                status=PreActionStatus.BYPASSED,
                idempotency_key=idempotency_key,
                cached_receipt=cached_receipt,
                reason=f"Replaying cached execution receipt (provider_id={cached_receipt.provider_receipt_id})",
            )

        # 2. Check single-use pre-authorization token
        with self._lock:
            if auth_token and self._authorized_tokens.get(auth_token) == idempotency_key:
                del self._authorized_tokens[auth_token]
                logger.info("Pre-action authorized via valid token for tool %s", tool_name)
                return PreActionEvaluationResult(
                    allowed=True,
                    status=PreActionStatus.APPROVED,
                    idempotency_key=idempotency_key,
                    auth_token=auth_token,
                    reason="Pre-action authorization token verified and consumed",
                )

        # 3. Intercept and issue challenge
        challenge_id = f"chal_{uuid4().hex[:16]}"
        summary = f"Intercepted irreversible action: {tool_name} with {len(arguments)} parameters"
        challenge = PreActionChallenge(
            challenge_id=challenge_id,
            session_id=session_id,
            tool_name=tool_name,
            arguments=arguments,
            idempotency_key=idempotency_key,
            risk_level=PreActionRiskLevel.HIGH,
            summary=summary,
        )

        with self._lock:
            self._challenges[challenge_id] = challenge
            self._challenge_statuses[challenge_id] = PreActionStatus.PENDING

        logger.warning(
            "Action intercepted: tool=%s, challenge_id=%s, idempotency_key=%s",
            tool_name,
            challenge_id,
            idempotency_key,
        )
        return PreActionEvaluationResult(
            allowed=False,
            status=PreActionStatus.PENDING,
            idempotency_key=idempotency_key,
            challenge=challenge,
            reason="External mutating action suspended awaiting explicit authorization",
        )

    def authorize_challenge(self, challenge_id: str, reviewer_id: str) -> str:
        """Approve an intercepted challenge and issue a single-use authorization token."""
        with self._lock:
            challenge = self._challenges.get(challenge_id)
            if challenge is None:
                raise ValueError(f"Challenge not found: {challenge_id}")
            if challenge.is_expired():
                self._challenge_statuses[challenge_id] = PreActionStatus.EXPIRED
                raise PreActionDeniedError(challenge_id, "Challenge has expired")

            token = f"tok_{uuid4().hex}"
            self._authorized_tokens[token] = challenge.idempotency_key
            self._challenge_statuses[challenge_id] = PreActionStatus.APPROVED
            logger.info("Challenge %s approved by %s, token issued", challenge_id, reviewer_id)
            return token

    def reject_challenge(self, challenge_id: str, reason: str) -> None:
        """Explicitly reject an intercepted challenge."""
        with self._lock:
            if challenge_id not in self._challenges:
                raise ValueError(f"Challenge not found: {challenge_id}")
            self._challenge_statuses[challenge_id] = PreActionStatus.REJECTED
            logger.info("Challenge %s rejected: %s", challenge_id, reason)

    def get_challenge(self, challenge_id: str) -> PreActionChallenge | None:
        """Retrieve challenge by ID."""
        with self._lock:
            return self._challenges.get(challenge_id)

    def get_challenge_status(self, challenge_id: str) -> PreActionStatus | None:
        """Retrieve status of challenge."""
        with self._lock:
            return self._challenge_statuses.get(challenge_id)

    def list_pending_challenges(self) -> list[PreActionChallenge]:
        """List all currently pending and unexpired challenges."""
        now = time.time()
        with self._lock:
            return [
                c
                for cid, c in self._challenges.items()
                if self._challenge_statuses.get(cid) == PreActionStatus.PENDING and not c.is_expired(now)
            ]

    def record_execution_receipt(
        self,
        idempotency_key: str,
        tool_name: str,
        provider_receipt_id: str,
        output_summary: str,
        challenge_id: str | None = None,
    ) -> ActionReceipt:
        """Record external execution receipt to prevent future duplicate execution."""
        receipt = ActionReceipt(
            idempotency_key=idempotency_key,
            tool_name=tool_name,
            provider_receipt_id=provider_receipt_id,
            status="completed",
            output_summary=output_summary,
            challenge_id=challenge_id,
        )
        self._receipt_cache.register_receipt(receipt)
        return receipt

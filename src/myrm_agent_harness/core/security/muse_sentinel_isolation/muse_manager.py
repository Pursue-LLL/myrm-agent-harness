"""Integrated Manager for Muse-Style Secure VM Isolation and Sentinel Suite."""

from __future__ import annotations

import threading
import uuid

from .sentinel_reviewer import SentinelOutboundReviewer
from .single_use_proxy import SingleUseCredentialProxy
from .types import (
    OutboundTrafficPayload,
    SandboxIsolationTier,
    SecureVmProfile,
    SentinelReviewResult,
    SingleUseToken,
    TokenRedemptionResult,
    TokenType,
)


class MuseSecureVmManager:
    """Orchestrates dedicated sandbox environments, pre-outbound Sentinel, and single-use proxies."""

    def __init__(
        self,
        sentinel: SentinelOutboundReviewer | None = None,
        proxy: SingleUseCredentialProxy | None = None,
    ) -> None:
        self._sentinel = sentinel or SentinelOutboundReviewer()
        self._proxy = proxy or SingleUseCredentialProxy()
        self._lock = threading.Lock()
        self._vms: dict[str, SecureVmProfile] = {}
        self._user_to_vm: dict[str, str] = {}

    @property
    def sentinel(self) -> SentinelOutboundReviewer:
        """Access Sentinel reviewer watchdog."""
        return self._sentinel

    @property
    def proxy(self) -> SingleUseCredentialProxy:
        """Access Single-Use Credential Proxy."""
        return self._proxy

    def register_vm(
        self,
        user_id: str,
        isolation_tier: SandboxIsolationTier = SandboxIsolationTier.DEDICATED_SECURE_VM,
        volume_mount: str | None = None,
    ) -> SecureVmProfile:
        """Register or provision a dedicated secure VM/container descriptor for a user."""
        resolved_volume = volume_mount or f"/mnt/volumes/users/{user_id}/persistent"
        vm_id = f"muse_vm_{uuid.uuid4().hex[:12]}"

        profile = SecureVmProfile(
            vm_id=vm_id,
            user_id=user_id,
            isolation_tier=isolation_tier,
            volume_mount=resolved_volume,
            egress_mode="sentinel_proxy",
            credential_sealed=True,
        )

        with self._lock:
            self._vms[vm_id] = profile
            self._user_to_vm[user_id] = vm_id

        return profile

    def get_vm(self, vm_id: str) -> SecureVmProfile | None:
        """Lookup VM by vm_id."""
        with self._lock:
            return self._vms.get(vm_id)

    def get_user_vm(self, user_id: str) -> SecureVmProfile | None:
        """Lookup VM by user_id."""
        with self._lock:
            vm_id = self._user_to_vm.get(user_id)
            if vm_id is None:
                return None
            return self._vms.get(vm_id)

    def list_vms(self) -> list[SecureVmProfile]:
        """List all active VM profiles."""
        with self._lock:
            return list(self._vms.values())

    def review_outbound(
        self, payload: OutboundTrafficPayload
    ) -> SentinelReviewResult:
        """Delegate outbound traffic frame to Sentinel reviewer."""
        return self._sentinel.review_outbound_traffic(payload)

    def issue_single_use_credential(
        self,
        token_type: TokenType = TokenType.VIRTUAL_PAYMENT_CARD,
        max_amount: float = 100.0,
        currency: str = "USD",
        bound_recipient: str = "*",
        ttl_seconds: int = 300,
    ) -> SingleUseToken:
        """Delegate single-use token issuance to credential proxy."""
        return self._proxy.issue_token(
            token_type=token_type,
            max_amount=max_amount,
            currency=currency,
            bound_recipient=bound_recipient,
            ttl_seconds=ttl_seconds,
        )

    def redeem_single_use_credential(
        self,
        virtual_token: str,
        amount: float,
        currency: str,
        recipient: str,
    ) -> TokenRedemptionResult:
        """Delegate single-use credential redemption and validation to proxy."""
        return self._proxy.redeem_token(
            virtual_token=virtual_token,
            amount=amount,
            currency=currency,
            recipient=recipient,
        )

"""
[POS] src/myrm_agent_harness/core/security/ephemeral_identity_voucher/merchant_locked_voucher_manager.py
[INPUT] time, secrets, uuid, urllib.parse, types
[OUTPUT] MerchantLockedVoucherManager

Engine for generating and enforcing domain-locked, single-use, capped monetary vouchers.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import secrets
import time
import uuid
from urllib.parse import urlparse

from .types import (
    EphemeralIdentityMetrics,
    MerchantLockedVoucher,
    VoucherStatus,
)


class MerchantLockedVoucherManager:
    """Manages single-use, domain-bound virtual payment vouchers with strict financial limits."""

    DEFAULT_VOUCHER_TTL_SECONDS: float = 600.0

    def __init__(self, metrics: EphemeralIdentityMetrics | None = None) -> None:
        self._vouchers: dict[str, MerchantLockedVoucher] = {}
        self._metrics: EphemeralIdentityMetrics = (
            metrics if metrics is not None else EphemeralIdentityMetrics()
        )

    @property
    def metrics(self) -> EphemeralIdentityMetrics:
        """Operational metrics reference."""
        return self._metrics

    @staticmethod
    def _normalize_domain(domain_or_url: str) -> str:
        """Extract and normalize host domain to prevent bypass via port or path."""
        candidate = domain_or_url.strip().lower()
        if "://" in candidate:
            parsed = urlparse(candidate)
            host = parsed.hostname or ""
        else:
            host = candidate.split("/")[0].split(":")[0]
        return host

    @staticmethod
    def _domain_matches(target_domain: str, requested_domain: str) -> bool:
        """Determine if requested domain satisfies target domain constraint.

        Allows exact host match or legitimate subdomain match if target starts with wildcards.
        """
        target = MerchantLockedVoucherManager._normalize_domain(target_domain)
        req = MerchantLockedVoucherManager._normalize_domain(requested_domain)
        if target == req:
            return True
        return bool(req.endswith("." + target))

    def issue_voucher(
        self,
        identity_id: str,
        target_merchant_domain: str,
        max_authorized_amount: float,
        currency: str = "USD",
        ttl_seconds: float = DEFAULT_VOUCHER_TTL_SECONDS,
    ) -> MerchantLockedVoucher:
        """Issue a fresh single-use payment voucher strictly bound to a merchant domain."""
        now = time.time()
        effective_ttl = max(10.0, ttl_seconds)
        expires_at = now + effective_ttl
        normalized_domain = self._normalize_domain(target_merchant_domain)

        voucher_id = f"vch-{uuid.uuid4().hex[:12]}"
        single_use_token = secrets.token_urlsafe(32)

        voucher = MerchantLockedVoucher(
            voucher_id=voucher_id,
            identity_id=identity_id,
            target_merchant_domain=normalized_domain,
            max_authorized_amount=max(0.0, max_authorized_amount),
            currency=currency.upper(),
            single_use_token=single_use_token,
            created_at_epoch=now,
            expires_at_epoch=expires_at,
            status=VoucherStatus.ISSUED,
            redeemed_amount=0.0,
            merchant_order_ref=None,
        )
        self._vouchers[voucher_id] = voucher
        self._metrics.vouchers_issued_total += 1
        return voucher

    def redeem_voucher(
        self,
        voucher_id: str,
        single_use_token: str,
        request_domain: str,
        requested_amount: float,
        order_ref: str | None = None,
    ) -> tuple[bool, VoucherStatus, str, MerchantLockedVoucher | None]:
        """Validate and redeem a single-use payment voucher against domain and amount limits.

        Returns:
            Tuple of (is_success, resulting_status, reason, updated_voucher_or_none).
        """
        voucher = self._vouchers.get(voucher_id)
        if voucher is None:
            self._metrics.vouchers_rejected_total += 1
            return (
                False,
                VoucherStatus.VOIDED,
                f"Voucher {voucher_id} not found",
                None,
            )

        now = time.time()

        # Check expiration
        if voucher.status == VoucherStatus.ISSUED and now >= voucher.expires_at_epoch:
            expired_v = MerchantLockedVoucher(
                voucher_id=voucher.voucher_id,
                identity_id=voucher.identity_id,
                target_merchant_domain=voucher.target_merchant_domain,
                max_authorized_amount=voucher.max_authorized_amount,
                currency=voucher.currency,
                single_use_token=voucher.single_use_token,
                created_at_epoch=voucher.created_at_epoch,
                expires_at_epoch=voucher.expires_at_epoch,
                status=VoucherStatus.EXPIRED,
                redeemed_amount=0.0,
                merchant_order_ref=None,
            )
            self._vouchers[voucher_id] = expired_v
            self._metrics.vouchers_rejected_total += 1
            return (
                False,
                VoucherStatus.EXPIRED,
                "Voucher validity window expired",
                expired_v,
            )

        # Check replay prevention
        if voucher.status != VoucherStatus.ISSUED:
            self._metrics.vouchers_rejected_total += 1
            return (
                False,
                voucher.status,
                f"Voucher cannot be redeemed: state is {voucher.status.value}",
                voucher,
            )

        # Validate token
        if not secrets.compare_digest(voucher.single_use_token, single_use_token):
            self._metrics.vouchers_rejected_total += 1
            return (
                False,
                VoucherStatus.VOIDED,
                "Single-use token mismatch",
                voucher,
            )

        # Domain boundary lock enforcement
        if not self._domain_matches(voucher.target_merchant_domain, request_domain):
            domain_mismatch_v = MerchantLockedVoucher(
                voucher_id=voucher.voucher_id,
                identity_id=voucher.identity_id,
                target_merchant_domain=voucher.target_merchant_domain,
                max_authorized_amount=voucher.max_authorized_amount,
                currency=voucher.currency,
                single_use_token=voucher.single_use_token,
                created_at_epoch=voucher.created_at_epoch,
                expires_at_epoch=voucher.expires_at_epoch,
                status=VoucherStatus.DOMAIN_MISMATCH,
                redeemed_amount=0.0,
                merchant_order_ref=order_ref,
            )
            self._vouchers[voucher_id] = domain_mismatch_v
            self._metrics.vouchers_rejected_total += 1
            return (
                False,
                VoucherStatus.DOMAIN_MISMATCH,
                (
                    f"Merchant domain lock violation: requested '{request_domain}' does "
                    f"not match locked '{voucher.target_merchant_domain}'"
                ),
                domain_mismatch_v,
            )

        # Financial limit enforcement
        if (
            requested_amount <= 0.0
            or requested_amount > voucher.max_authorized_amount
        ):
            limit_exceeded_v = MerchantLockedVoucher(
                voucher_id=voucher.voucher_id,
                identity_id=voucher.identity_id,
                target_merchant_domain=voucher.target_merchant_domain,
                max_authorized_amount=voucher.max_authorized_amount,
                currency=voucher.currency,
                single_use_token=voucher.single_use_token,
                created_at_epoch=voucher.created_at_epoch,
                expires_at_epoch=voucher.expires_at_epoch,
                status=VoucherStatus.LIMIT_EXCEEDED,
                redeemed_amount=0.0,
                merchant_order_ref=order_ref,
            )
            self._vouchers[voucher_id] = limit_exceeded_v
            self._metrics.vouchers_rejected_total += 1
            return (
                False,
                VoucherStatus.LIMIT_EXCEEDED,
                (
                    f"Monetary cap breach: requested {requested_amount} exceeds "
                    f"authorized max {voucher.max_authorized_amount} {voucher.currency}"
                ),
                limit_exceeded_v,
            )

        # Successful redemption - transition to single-use REDEEMED
        redeemed_v = MerchantLockedVoucher(
            voucher_id=voucher.voucher_id,
            identity_id=voucher.identity_id,
            target_merchant_domain=voucher.target_merchant_domain,
            max_authorized_amount=voucher.max_authorized_amount,
            currency=voucher.currency,
            single_use_token=voucher.single_use_token,
            created_at_epoch=voucher.created_at_epoch,
            expires_at_epoch=voucher.expires_at_epoch,
            status=VoucherStatus.REDEEMED,
            redeemed_amount=requested_amount,
            merchant_order_ref=order_ref,
        )
        self._vouchers[voucher_id] = redeemed_v
        self._metrics.vouchers_redeemed_total += 1
        return (
            True,
            VoucherStatus.REDEEMED,
            "Voucher redeemed successfully within domain and monetary limits",
            redeemed_v,
        )

    def void_voucher(self, voucher_id: str, reason: str = "Admin void") -> bool:
        """Void an active voucher before redemption."""
        voucher = self._vouchers.get(voucher_id)
        if voucher is None or voucher.status != VoucherStatus.ISSUED:
            return False

        voided_v = MerchantLockedVoucher(
            voucher_id=voucher.voucher_id,
            identity_id=voucher.identity_id,
            target_merchant_domain=voucher.target_merchant_domain,
            max_authorized_amount=voucher.max_authorized_amount,
            currency=voucher.currency,
            single_use_token=voucher.single_use_token,
            created_at_epoch=voucher.created_at_epoch,
            expires_at_epoch=voucher.expires_at_epoch,
            status=VoucherStatus.VOIDED,
            redeemed_amount=0.0,
            merchant_order_ref=None,
        )
        self._vouchers[voucher_id] = voided_v
        return True

    def get_voucher(self, voucher_id: str) -> MerchantLockedVoucher | None:
        """Lookup voucher by ID."""
        return self._vouchers.get(voucher_id)

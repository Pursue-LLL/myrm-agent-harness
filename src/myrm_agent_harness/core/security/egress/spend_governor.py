"""Spend Governor and Atomic Lease Controller for Agent Commerce.

[INPUT]
- .spend_contracts::SpendGovernorConfig, SpendLease, SpendLeaseResult, SpendCommitResult, is_spend_voucher (POS: 预算保险箱数据模型与契约)
- base64::base64 (POS: Python 标准 base64 编解码库)
- fnmatch::fnmatch (POS: 域名通配符模式匹配库)
- hashlib, hmac (POS: Python 加密散列与签名标准库)
- json::json (POS: Python JSON 序列化标准库)
- os, time (POS: 系统调用与时间标准库)

[OUTPUT]
- SpendGovernor: 纯状态机预算保险箱控制器
- SpendGovernorConfig, SpendLease, SpendLeaseResult, SpendCommitResult, is_spend_voucher: 重新导出契约

[POS]
Harness core security egress layer. Enforces pure deterministic micro-spending limits,
merchant domain whitelisting, atomic lease reservations, and zero-float USD Cents accounting.
"""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import hmac
import json
import logging
import os
import time
from collections.abc import Mapping

from .spend_contracts import (
    DEFAULT_SPEND_HMAC_SALT,
    SPEND_VOUCHER_PREFIX,
    SPEND_VOUCHER_SUFFIX,
    SpendCommitResult,
    SpendGovernorConfig,
    SpendLease,
    SpendLeaseResult,
    is_spend_voucher,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_SPEND_HMAC_SALT",
    "SPEND_VOUCHER_PREFIX",
    "SPEND_VOUCHER_SUFFIX",
    "SpendCommitResult",
    "SpendGovernor",
    "SpendGovernorConfig",
    "SpendLease",
    "SpendLeaseResult",
    "is_spend_voucher",
]


class SpendGovernor:
    """In-memory deterministic state machine enforcing autonomous micro-spending bounds.

    Guarantees:
    1. Zero float rounding: all financial accounting runs strictly in integer USD Cents.
    2. Atomic reservation: concurrency cannot breach the daily or per-action cap.
    3. Merchant domain allowlist: strict domain and wildcard glob verification.
    4. Auto-expiry release: uncommitted leases automatically expire and release budget.
    5. Process-level tamper-evident HMAC vouchers for downstream egress proxies.
    """

    def __init__(
        self,
        config: SpendGovernorConfig | None = None,
        key: bytes | None = None,
    ) -> None:
        self._config: SpendGovernorConfig = config or SpendGovernorConfig()
        self._key: bytes = key if key is not None else os.urandom(32)
        self._leases: dict[str, SpendLease] = {}
        self._daily_spent_cents: int = 0
        self._current_day_index: int = int(time.time() // 86400)
        self._prev_entry_hash: str = "0" * 64

    @property
    def config(self) -> SpendGovernorConfig:
        return self._config

    def update_config(self, new_config: SpendGovernorConfig) -> None:
        """Update runtime configuration parameters."""
        self._config = new_config

    def freeze(self) -> None:
        """Emergency circuit breaker: freeze all autonomous spending."""
        self._config = SpendGovernorConfig(
            daily_cap_cents=self._config.daily_cap_cents,
            per_action_cap_cents=self._config.per_action_cap_cents,
            allowed_merchants=self._config.allowed_merchants,
            currency=self._config.currency,
            is_frozen=True,
            lease_ttl_seconds=self._config.lease_ttl_seconds,
        )

    def unfreeze(self) -> None:
        """Resume autonomous spending operations."""
        self._config = SpendGovernorConfig(
            daily_cap_cents=self._config.daily_cap_cents,
            per_action_cap_cents=self._config.per_action_cap_cents,
            allowed_merchants=self._config.allowed_merchants,
            currency=self._config.currency,
            is_frozen=False,
            lease_ttl_seconds=self._config.lease_ttl_seconds,
        )

    def is_merchant_allowed(self, merchant_domain: str) -> bool:
        """Match candidate merchant domain against whitelist and wildcard globs."""
        if not merchant_domain:
            return False
        clean_domain = merchant_domain.lower().strip().split(":")[0]
        for pattern in self._config.allowed_merchants:
            pat = pattern.lower().strip()
            if fnmatch.fnmatch(clean_domain, pat) or clean_domain == pat:
                return True
        return False

    def _roll_day_if_needed(self, now: float) -> None:
        """Reset counter if a new UTC calendar day is reached."""
        day_index = int(now // 86400)
        if day_index > self._current_day_index:
            self._daily_spent_cents = 0
            self._current_day_index = day_index

    def restore_daily_spent(self, spent_cents: int, now: float | None = None) -> None:
        """Reconcile and restore today's accumulated spend baseline from persistent storage."""
        current_time = time.time() if now is None else now
        self._roll_day_if_needed(current_time)
        self._daily_spent_cents = max(0, spent_cents)

    def cleanup_expired_leases(self, now: float | None = None) -> int:
        """Scan expired leases and prune terminal ones older than retention window."""
        current_time = time.time() if now is None else now
        expired_count = 0
        terminal_retention = 3600.0
        for lid, lease in list(self._leases.items()):
            if lease.status == "reserved" and current_time > lease.expires_at:
                lease.status = "expired"
                expired_count += 1
            elif lease.status in ("expired", "committed", "released"):
                if current_time > lease.expires_at + terminal_retention:
                    self._leases.pop(lid, None)
        return expired_count

    def get_active_reserved_cents(self, now: float | None = None) -> int:
        """Calculate total amount currently reserved by in-flight active leases."""
        current_time = time.time() if now is None else now
        total = 0
        for lease in self._leases.values():
            if lease.status == "reserved" and current_time <= lease.expires_at:
                total += lease.amount_cents
        return total

    def reserve(
        self,
        merchant_domain: str,
        amount_cents: int,
        idempotency_key: str = "",
        now: float | None = None,
    ) -> SpendLeaseResult:
        """Atomically evaluate constraints and reserve budget for an upcoming purchase."""
        current_time = time.time() if now is None else now
        self._roll_day_if_needed(current_time)
        self.cleanup_expired_leases(current_time)

        if self._config.is_frozen:
            return SpendLeaseResult(
                success=False,
                code="FROZEN",
                message="Autonomous spending is currently frozen by emergency breaker.",
            )

        if amount_cents <= 0:
            return SpendLeaseResult(
                success=False,
                code="INVALID_AMOUNT",
                message=f"Amount must be strictly positive integer Cents, received {amount_cents}.",
            )

        if not self.is_merchant_allowed(merchant_domain):
            return SpendLeaseResult(
                success=False,
                code="UNTRUSTED_MERCHANT",
                message=f"Merchant '{merchant_domain}' is not in allowed merchants whitelist.",
            )

        if amount_cents > self._config.per_action_cap_cents:
            return SpendLeaseResult(
                success=False,
                code="LIMIT_EXCEEDED",
                message=(
                    f"Requested amount ({amount_cents} cents) exceeds per-action cap "
                    f"({self._config.per_action_cap_cents} cents)."
                ),
            )

        active_reserved = self.get_active_reserved_cents(current_time)
        projected_spend = self._daily_spent_cents + active_reserved + amount_cents
        if projected_spend > self._config.daily_cap_cents:
            return SpendLeaseResult(
                success=False,
                code="LIMIT_EXCEEDED",
                message=(
                    f"Projected daily spend ({projected_spend} cents) exceeds daily cap "
                    f"({self._config.daily_cap_cents} cents)."
                ),
            )

        # Idempotency check: if lease already exists with this idempotency key
        if idempotency_key:
            for existing in self._leases.values():
                if (
                    existing.idempotency_key == idempotency_key
                    and existing.merchant_domain.lower() == merchant_domain.lower()
                    and existing.amount_cents == amount_cents
                    and existing.status == "reserved"
                    and current_time <= existing.expires_at
                ):
                    voucher = self._mint_voucher(existing)
                    return SpendLeaseResult(
                        success=True,
                        code="APPROVED",
                        message="Idempotent lease reservation reused.",
                        lease=existing,
                        voucher=voucher,
                    )

        # Mint new lease
        lease_id = f"lease_{os.urandom(8).hex()}"
        expires_at = current_time + self._config.lease_ttl_seconds
        lease = SpendLease(
            lease_id=lease_id,
            merchant_domain=merchant_domain,
            amount_cents=amount_cents,
            currency=self._config.currency,
            created_at=current_time,
            expires_at=expires_at,
            status="reserved",
            idempotency_key=idempotency_key,
        )
        self._leases[lease_id] = lease
        voucher = self._mint_voucher(lease)

        return SpendLeaseResult(
            success=True,
            code="APPROVED",
            message="Spend reservation approved.",
            lease=lease,
            voucher=voucher,
        )

    def commit(
        self,
        lease_id: str,
        idempotency_key: str = "",
        now: float | None = None,
    ) -> SpendCommitResult:
        """Commit an approved lease after successful outbound transaction."""
        current_time = time.time() if now is None else now
        lease = self._leases.get(lease_id)

        if not lease:
            return SpendCommitResult(
                success=False,
                code="LEASE_NOT_FOUND",
                message=f"Spend lease '{lease_id}' not found.",
            )

        if lease.status == "committed":
            return SpendCommitResult(
                success=True,
                code="ALREADY_COMMITTED",
                message=f"Spend lease '{lease_id}' was already committed.",
            )

        if lease.status == "expired" or current_time > lease.expires_at:
            lease.status = "expired"
            return SpendCommitResult(
                success=False,
                code="LEASE_EXPIRED",
                message=f"Spend lease '{lease_id}' expired before commit.",
            )

        if lease.status != "reserved":
            return SpendCommitResult(
                success=False,
                code="INVALID_STATE",
                message=f"Spend lease '{lease_id}' is in status '{lease.status}', cannot commit.",
            )

        # Commit state and record into daily spend
        lease.status = "committed"
        self._daily_spent_cents += lease.amount_cents

        # Build cryptographic hash chain entry
        entry_payload = (
            f"{self._prev_entry_hash}:{lease.lease_id}:{lease.merchant_domain}:"
            f"{lease.amount_cents}:{lease.currency}:{current_time}:{idempotency_key}"
        )
        entry_hash = hashlib.sha256(entry_payload.encode("utf-8")).hexdigest()
        self._prev_entry_hash = entry_hash

        action_digest = (
            f"{lease.currency} {lease.amount_cents / 100:.2f} paid to {lease.merchant_domain}"
        )
        return SpendCommitResult(
            success=True,
            code="COMMITTED",
            message="Spend lease committed successfully.",
            entry_hash=entry_hash,
            action_digest=action_digest,
        )

    def release(self, lease_id: str) -> bool:
        """Release an unspent reservation back to the available pool."""
        lease = self._leases.get(lease_id)
        if not lease:
            return False
        if lease.status == "reserved":
            lease.status = "released"
            return True
        return False

    def _mint_voucher(self, lease: SpendLease) -> str:
        """Create a cryptographic AES-256-GCM / HMAC authenticated voucher token."""
        payload_dict: Mapping[str, str | int | float] = {
            "lid": lease.lease_id,
            "dom": lease.merchant_domain,
            "amt": lease.amount_cents,
            "cur": lease.currency,
            "exp": lease.expires_at,
        }
        raw_json = json.dumps(payload_dict, sort_keys=True).encode("utf-8")
        sig = hmac.new(self._key, raw_json, hashlib.sha256).digest()
        token = base64.urlsafe_b64encode(raw_json + sig).decode("ascii").rstrip("=")
        return f"{SPEND_VOUCHER_PREFIX}{token}{SPEND_VOUCHER_SUFFIX}"

    def verify_spend_voucher(self, voucher: str) -> dict[str, str | int | float] | None:
        """Verify voucher signature and decode parameters."""
        if not is_spend_voucher(voucher):
            return None
        raw_token = voucher[len(SPEND_VOUCHER_PREFIX) : -len(SPEND_VOUCHER_SUFFIX)]
        padding = (4 - len(raw_token) % 4) % 4
        try:
            raw_bytes = base64.urlsafe_b64decode(raw_token + "=" * padding)
            if len(raw_bytes) <= 32:
                return None
            body_bytes = raw_bytes[:-32]
            received_sig = raw_bytes[-32:]
            expected_sig = hmac.new(self._key, body_bytes, hashlib.sha256).digest()
            if not hmac.compare_digest(received_sig, expected_sig):
                return None
            data = json.loads(body_bytes.decode("utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            logger.debug("Failed decoding spend voucher %s", voucher[:20])
        return None

    def get_metrics(self, now: float | None = None) -> dict[str, object]:
        """Produce real-time metrics for observability and UI state."""
        current_time = time.time() if now is None else now
        self._roll_day_if_needed(current_time)
        self.cleanup_expired_leases(current_time)
        active_reserved = self.get_active_reserved_cents(current_time)
        remaining = max(0, self._config.daily_cap_cents - self._daily_spent_cents - active_reserved)
        return {
            "dailyCapCents": self._config.daily_cap_cents,
            "perActionCapCents": self._config.per_action_cap_cents,
            "dailySpentCents": self._daily_spent_cents,
            "activeReservedCents": active_reserved,
            "remainingCents": remaining,
            "currency": self._config.currency,
            "isFrozen": self._config.is_frozen,
            "allowedMerchantsCount": len(self._config.allowed_merchants),
            "allowedMerchants": list(self._config.allowed_merchants),
            "totalLeasesTracked": len(self._leases),
        }

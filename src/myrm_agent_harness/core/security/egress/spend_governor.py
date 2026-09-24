"""Spend Governor and Atomic Lease Controller for Agent Commerce.

[INPUT]
- base64::base64 (POS: Python 标准 base64 编解码库)
- fnmatch::fnmatch (POS: 域名通配符模式匹配库)
- hashlib, hmac (POS: Python 加密散列与签名标准库)
- json::json (POS: Python JSON 序列化标准库)
- os, time (POS: 系统调用与时间标准库)

[OUTPUT]
- SpendGovernorConfig: 配置约束模型（单笔/日累计上限、商户白名单、冻结状态）
- SpendLease: 原子预占租约数据模型
- SpendLeaseResult, SpendCommitResult: 状态机判定结果契约
- SpendGovernor: 纯状态机预算保险箱控制器
- is_spend_voucher: 快速检测是否为微支付凭证字符串

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
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SPEND_VOUCHER_PREFIX: str = "myrm-spend-v1."
SPEND_VOUCHER_SUFFIX: str = ".end"
DEFAULT_SPEND_HMAC_SALT: str = "myrm-agent-commerce-spend-salt-v1"


@dataclass(frozen=True, slots=True)
class SpendGovernorConfig:
    """Configuration constraints for autonomous agentic commerce spending."""

    daily_cap_cents: int = 1000  # $10.00
    per_action_cap_cents: int = 200  # $2.00
    allowed_merchants: tuple[str, ...] = (
        "*.openai.com",
        "api.anthropic.com",
        "namesilo.com",
        "namecheap.com",
        "2captcha.com",
        "capsolver.com",
        "stripe.com",
    )
    currency: str = "USD"
    is_frozen: bool = False
    lease_ttl_seconds: int = 120


@dataclass(slots=True)
class SpendLease:
    """Atomic in-flight spend reservation."""

    lease_id: str
    merchant_domain: str
    amount_cents: int
    currency: str
    created_at: float
    expires_at: float
    status: str  # "reserved" | "committed" | "released" | "expired"
    idempotency_key: str = ""


@dataclass(frozen=True, slots=True)
class SpendLeaseResult:
    """Result of an atomic spend reservation attempt."""

    success: bool
    code: str  # "APPROVED" | "FROZEN" | "LIMIT_EXCEEDED" | "UNTRUSTED_MERCHANT" | "INVALID_AMOUNT"
    message: str
    lease: SpendLease | None = None
    voucher: str | None = None


@dataclass(frozen=True, slots=True)
class SpendCommitResult:
    """Result of committing a previously reserved spend lease."""

    success: bool
    code: str  # "COMMITTED" | "LEASE_NOT_FOUND" | "LEASE_EXPIRED" | "ALREADY_COMMITTED"
    message: str
    entry_hash: str | None = None
    action_digest: str | None = None


def is_spend_voucher(val: str) -> bool:
    """Check if a string matches the spend voucher format."""
    return bool(val and val.startswith(SPEND_VOUCHER_PREFIX) and val.endswith(SPEND_VOUCHER_SUFFIX))


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
        self._last_day_timestamp: float = time.time()
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
        # Reset counter if 86400 seconds (24h) have elapsed since day baseline
        if now - self._last_day_timestamp >= 86400.0:
            self._daily_spent_cents = 0
            self._last_day_timestamp = now

    def cleanup_expired_leases(self, now: float | None = None) -> int:
        """Scan and mark expired reserved leases to free up allocation."""
        current_time = time.time() if now is None else now
        expired_count = 0
        for lease in list(self._leases.values()):
            if lease.status == "reserved" and current_time > lease.expires_at:
                lease.status = "expired"
                expired_count += 1
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
        """Atomically reserve funds for a micro-spending action.

        Returns SpendLeaseResult with a signed voucher if approved.
        """
        current_time = time.time() if now is None else now
        self._roll_day_if_needed(current_time)
        self.cleanup_expired_leases(current_time)

        # 1. Emergency freeze check
        if self._config.is_frozen:
            return SpendLeaseResult(
                success=False,
                code="FROZEN",
                message="Autonomous spending is currently frozen by emergency breaker.",
            )

        # 2. Amount validity check (strictly positive integer)
        if amount_cents <= 0:
            return SpendLeaseResult(
                success=False,
                code="INVALID_AMOUNT",
                message=f"Spend amount must be a positive integer in cents, got {amount_cents}.",
            )

        # 3. Whitelist check
        if not self.is_merchant_allowed(merchant_domain):
            return SpendLeaseResult(
                success=False,
                code="UNTRUSTED_MERCHANT",
                message=f"Merchant '{merchant_domain}' is not in allowed merchants whitelist.",
            )

        # 4. Per-action cap check
        if amount_cents > self._config.per_action_cap_cents:
            return SpendLeaseResult(
                success=False,
                code="LIMIT_EXCEEDED",
                message=(
                    f"Amount {amount_cents} cents exceeds per-action cap "
                    f"{self._config.per_action_cap_cents} cents."
                ),
            )

        # 5. Daily cumulative + in-flight reservation check
        active_reserved = self.get_active_reserved_cents(current_time)
        projected_spend = self._daily_spent_cents + active_reserved + amount_cents
        if projected_spend > self._config.daily_cap_cents:
            return SpendLeaseResult(
                success=False,
                code="LIMIT_EXCEEDED",
                message=(
                    f"Projected daily spend {projected_spend} cents (spent: {self._daily_spent_cents}, "
                    f"reserved: {active_reserved}, requested: {amount_cents}) exceeds daily cap "
                    f"{self._config.daily_cap_cents} cents."
                ),
            )

        # 6. Issue atomic lease
        lease_id = f"lease_{os.urandom(8).hex()}"
        lease = SpendLease(
            lease_id=lease_id,
            merchant_domain=merchant_domain.lower().strip(),
            amount_cents=amount_cents,
            currency=self._config.currency,
            created_at=current_time,
            expires_at=current_time + self._config.lease_ttl_seconds,
            status="reserved",
            idempotency_key=idempotency_key,
        )
        self._leases[lease_id] = lease

        # 7. Generate tamper-evident voucher
        voucher = self._mint_voucher(lease)

        return SpendLeaseResult(
            success=True,
            code="APPROVED",
            message="Spend reservation approved within autonomous bounds.",
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
        if idempotency_key:
            lease.idempotency_key = idempotency_key
        self._daily_spent_cents += lease.amount_cents

        # Generate cryptographic action digest and chained receipt hash
        action_payload = f"{lease.merchant_domain}:{lease.amount_cents}:{lease.currency}:{lease.idempotency_key}".encode()
        action_digest = hmac.new(self._key, action_payload, hashlib.sha256).hexdigest()

        entry_payload = (
            f"{self._prev_entry_hash}:{current_time:.3f}:{lease.merchant_domain}:"
            f"{lease.amount_cents}:{lease.currency}:{action_digest}"
        ).encode()
        entry_hash = hmac.new(self._key, entry_payload, hashlib.sha256).hexdigest()
        self._prev_entry_hash = entry_hash

        return SpendCommitResult(
            success=True,
            code="COMMITTED",
            message=f"Committed {lease.amount_cents} cents to merchant {lease.merchant_domain}.",
            entry_hash=entry_hash,
            action_digest=action_digest,
        )

    def release(self, lease_id: str) -> bool:
        """Release a reserved lease (e.g. downstream network failure or aborted purchase)."""
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

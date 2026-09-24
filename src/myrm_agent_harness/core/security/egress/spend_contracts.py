"""Data contracts and immutable primitives for Agentic Commerce Spending Governance.

[INPUT]
- dataclasses::dataclass (POS: Python 标准数据模型构造库)

[OUTPUT]
- SPEND_VOUCHER_PREFIX: 微支付凭证固定前缀
- SPEND_VOUCHER_SUFFIX: 微支付凭证固定后缀
- DEFAULT_SPEND_HMAC_SALT: 默认凭据防伪签名盐
- SpendGovernorConfig: 预算约束模型（单笔/日累计上限、商户白名单、冻结状态）
- SpendLease: 原子预占租约数据模型
- SpendLeaseResult: 租约申请判定结果契约
- SpendCommitResult: 租约核销结果契约
- is_spend_voucher: 微支付凭据快速格式判定函数

[POS]
Harness core security egress layer. Defines immutable data transfer models and token formats
for autonomous spending governors, ensuring zero-float integer accounting.
"""

from __future__ import annotations

from dataclasses import dataclass

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

"""Out-of-band checkout handoff and zero-model-touch payment security layer.

[INPUT]
- Cart, CartLine from myrm_agent_harness.backends.commerce.types
- Target URLs and payment providers (Stripe, hosted gateway, internal routes)

[OUTPUT]
- CheckoutHandoffMode: 结账手交模式枚举
- CheckoutTarget: 强类型安全结账目标 (url, provider, amount, currency, expires_at)
- CheckoutHandoffPayload: 完整结账手交载荷
- CheckoutCardPayload: 模型端安全展示卡片 (严格隔离支付URL)
- ZeroTouchHandoffEnricher: 零模型接触富化中枢，隔离支付凭据与 URL，防止钓鱼与篡改
- sanitize_checkout_for_model / inject_checkout_url_to_card: 宿主层安全注入函数

[POS]
Enterprise-grade checkout isolation adhering to PCI-DSS principles.
Model context never touches payment tokens, credentials, or destination URLs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
import re
from urllib.parse import urlparse

from myrm_agent_harness.backends.commerce.exceptions import CommerceError
from myrm_agent_harness.backends.commerce.types import Cart

PAYMENT_HANDOFF_GATE = "PAYMENT_HANDOFF_GATE"


class CheckoutHandoffMode(str, Enum):
    """Modes of out-of-band checkout completion."""

    REDIRECT = "redirect"
    QR_CODE = "qr_code"
    DEEP_LINK = "deep_link"
    EMBEDDED = "embedded"
    INTERNAL_ROUTE = "internal_route"
    HOSTED_GATEWAY = "hosted_gateway"
    MARKETPLACE_SPLIT = "marketplace_split"


@dataclass(frozen=True, slots=True)
class CheckoutTarget:
    """Safe payment destination link and metadata."""

    target_id: str
    provider: str
    url: str
    seller_id: str | None = None
    title: str = ""
    amount: float = 0.0
    currency: str = "USD"
    expires_at: datetime | None = None
    handoff_token: str | None = None


@dataclass(frozen=True, slots=True)
class CheckoutHandoffPayload:
    """Consolidated out-of-band checkout execution payload."""

    session_id: str
    checkout_url: str = ""
    cart_id: str = ""
    total_amount: float = 0.0
    currency: str = "USD"
    handoff_mode: CheckoutHandoffMode = CheckoutHandoffMode.REDIRECT
    targets: tuple[CheckoutTarget, ...] = ()
    note: str = ""
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def mode(self) -> CheckoutHandoffMode:
        return self.handoff_mode

    @property
    def target_count(self) -> int:
        return len(self.targets)


@dataclass(frozen=True, slots=True)
class CheckoutCardPayload:
    """Safe payload for LLM presentation, stripped of sensitive payment URLs."""

    session_id: str
    cart_id: str
    total_amount: float
    currency: str
    item_count: int
    has_checkout_link: bool = True
    handoff_mode: str = "redirect"


def sanitize_checkout_for_model(
    payload: CheckoutHandoffPayload,
    item_count: int = 1,
) -> CheckoutCardPayload:
    """Strip secret URLs and tokens so the model receives only safe metadata."""
    return CheckoutCardPayload(
        session_id=payload.session_id,
        cart_id=payload.cart_id,
        total_amount=payload.total_amount,
        currency=payload.currency,
        item_count=item_count,
        has_checkout_link=bool(payload.checkout_url or payload.targets),
        handoff_mode=payload.handoff_mode.value,
    )


def inject_checkout_url_to_card(
    model_card: CheckoutCardPayload,
    payload: CheckoutHandoffPayload,
) -> dict[str, object]:
    """Host presentation layer attaches real payment URL exclusively for client UI."""
    return {
        "session_id": model_card.session_id,
        "cart_id": model_card.cart_id,
        "total_amount": model_card.total_amount,
        "currency": model_card.currency,
        "item_count": model_card.item_count,
        "handoff_mode": model_card.handoff_mode,
        "checkout_url": payload.checkout_url,
        "has_checkout_link": model_card.has_checkout_link,
        "targets": [
            {
                "target_id": t.target_id,
                "provider": t.provider,
                "url": t.url,
                "seller_id": t.seller_id,
                "title": t.title,
                "amount": t.amount,
                "currency": t.currency,
                "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                "handoff_token": t.handoff_token,
            }
            for t in payload.targets
        ],
    }


@dataclass(frozen=True, slots=True)
class ZeroTouchHandoffEnvelope:
    """Enriched dual-view envelope isolating model reasoning from sensitive URLs."""

    model_context_summary: str
    client_render_payload: dict[str, object]
    gate_passed: bool = True


class ZeroTouchHandoffEnricher:
    """Security coordinator that isolates payment URLs and credentials from the LLM.

    The model only receives structured intent acknowledgment and monetary totals.
    Real payment URLs and tokens are injected exclusively into client_render_payload.
    """

    BLOCKED_SCHEME_PATTERN = re.compile(r"^(javascript|data|vbscript|file):", re.IGNORECASE)

    @classmethod
    def validate_target_url(cls, url: str) -> bool:
        """Validate destination URL to prevent XSS, phishing, or SSRF injections."""
        cleaned = url.strip()
        if not cleaned:
            return False
        if cls.BLOCKED_SCHEME_PATTERN.match(cleaned):
            return False

        if cleaned.startswith("/"):
            return not cleaned.startswith("//")

        parsed = urlparse(cleaned)
        if parsed.scheme.lower() not in ("https", "http"):
            return False
        if parsed.scheme.lower() == "http" and parsed.hostname not in ("localhost", "127.0.0.1"):
            return False
        return bool(parsed.netloc)

    @classmethod
    def enrich_checkout(
        cls,
        *,
        session_id: str,
        cart: Cart,
        mode: CheckoutHandoffMode,
        targets: list[CheckoutTarget],
        note: str = "",
    ) -> ZeroTouchHandoffEnvelope:
        """Enrich checkout with zero-model-touch guarantees.

        Raises:
            CommerceError: If the cart is empty or any target URL fails the security gate.
        """
        if not cart.lines:
            raise CommerceError(
                "Cannot initiate checkout: shopping cart is empty.",
                code="CART_EMPTY",
            )

        if not targets:
            raise CommerceError(
                "No checkout targets provided for handoff.",
                code="TARGETS_EMPTY",
            )

        sanitized_targets: list[CheckoutTarget] = []
        for target in targets:
            if not cls.validate_target_url(target.url):
                raise CommerceError(
                    f"Checkout target URL failed security gate [{PAYMENT_HANDOFF_GATE}]: {target.url}",
                    code="UNSAFE_CHECKOUT_URL",
                )
            sanitized_targets.append(target)

        total_amount = cart.subtotal
        currency = cart.currency

        payload = CheckoutHandoffPayload(
            session_id=session_id,
            checkout_url=sanitized_targets[0].url if sanitized_targets else "",
            cart_id=cart.cart_id,
            total_amount=total_amount,
            currency=currency,
            handoff_mode=mode,
            targets=tuple(sanitized_targets),
            note=note,
        )

        model_summary = (
            f"Checkout handoff initiated successfully. Total: {total_amount:.2f} {currency}. "
            f"Mode: {mode.value}. Safe destination cards rendered directly to customer UI. "
            f"Zero model contact enforced under {PAYMENT_HANDOFF_GATE}."
        )

        client_payload: dict[str, object] = {
            "component": "checkout_card",
            "cart_id": payload.cart_id,
            "session_id": payload.session_id,
            "mode": payload.mode.value,
            "total_amount": payload.total_amount,
            "currency": payload.currency,
            "note": payload.note,
            "created_at": payload.created_at.isoformat(),
            "targets": [
                {
                    "target_id": t.target_id,
                    "provider": t.provider,
                    "url": t.url,
                    "seller_id": t.seller_id,
                    "title": t.title,
                    "amount": t.amount,
                    "currency": t.currency,
                    "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                    "handoff_token": t.handoff_token,
                }
                for t in payload.targets
            ],
        }

        return ZeroTouchHandoffEnvelope(
            model_context_summary=model_summary,
            client_render_payload=client_payload,
            gate_passed=True,
        )

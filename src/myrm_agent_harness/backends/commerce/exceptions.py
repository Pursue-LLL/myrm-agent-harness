"""Commerce exception hierarchy.

[INPUT]
- (none)

[OUTPUT]
- CommerceError: 商业模块根异常
- NotOffered: 商店或当前上下文不提供该能力（业务语义拦截）
- Unavailable: 商品或变体暂时不可购买（如缺货）
- ChangeNotApplicable: 变更不适用于目标实体或系统
- InvalidStagedChange: 变更提案非法或已失效
- OptionsResolutionHeld: 多规格变体未决挂起异常（携带推荐芯片）
- CartCapExceeded: 购物车容量或条目超额拦截异常

[POS]
Commerce domain exception definitions for Storefront and Merchant backends.
"""

from __future__ import annotations


class CommerceError(Exception):
    """Base exception for all commerce backend operations."""

    def __init__(self, message: str, *, code: str = "COMMERCE_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class NotOffered(CommerceError):
    """Raised when an operation or capability is not offered by the store.

    This represents a valid business state (e.g. shipping policy not applicable,
    store does not offer localized fulfillment), not a system failure.
    """

    def __init__(self, message: str = "This capability is not offered by the store.") -> None:
        super().__init__(message, code="NOT_OFFERED")


class Unavailable(CommerceError):
    """Raised when an item, variant, or resource is temporarily unavailable.

    For example, when a product or variant is out of stock. The message should
    identify ids only to prevent prompt injection.
    """

    def __init__(
        self,
        message: str = "The requested item is currently unavailable.",
        *,
        item_id: str | None = None,
        available_variant_ids: list[str] | None = None,
    ) -> None:
        super().__init__(message, code="UNAVAILABLE")
        self.item_id = item_id
        self.available_variant_ids = available_variant_ids or []


class ChangeNotApplicable(CommerceError):
    """Raised when a merchant proposal does not apply to the target entity."""

    def __init__(self, message: str = "The proposed change cannot be applied to this item.") -> None:
        super().__init__(message, code="CHANGE_NOT_APPLICABLE")


class InvalidStagedChange(CommerceError):
    """Raised when a staged proposal is invalid, expired, or corrupted."""

    def __init__(self, message: str = "The staged change proposal is invalid.") -> None:
        super().__init__(message, code="INVALID_STAGED_CHANGE")


class OptionsResolutionHeld(CommerceError):
    """Raised when an operation targets a multi-option product without selecting a variant.

    Carries selectable suggestion chips for human/agent rapid convergence.
    """

    def __init__(
        self,
        message: str = "Product has variants and requires selecting options.",
        *,
        product_id: str,
        options: list[str] | None = None,
        available_variants: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message, code="OPTIONS_RESOLUTION_HELD")
        self.product_id = product_id
        self.options = options or []
        self.available_variants = available_variants or []


class CartCapExceeded(CommerceError):
    """Raised when cart item quantity or line limit is breached."""

    def __init__(
        self,
        message: str = "Cart capacity limit exceeded.",
        *,
        cap_type: str = "max_quantity_per_item",
        limit: int,
        attempted: int,
    ) -> None:
        super().__init__(message, code="CART_CAP_EXCEEDED")
        self.cap_type = cap_type
        self.limit = limit
        self.attempted = attempted


class GuardrailViolationError(CommerceError):
    """Raised when a merchant proposed change violates pricing, promotion, or inventory safety thresholds."""

    def __init__(
        self,
        message: str = "Merchant operation rejected by safety guardrails.",
        *,
        rule: str,
        threshold: float | int | str,
        attempted: float | int | str,
        compliant_alternative: str | None = None,
    ) -> None:
        super().__init__(message, code="GUARDRAIL_VIOLATION")
        self.rule = rule
        self.threshold = threshold
        self.attempted = attempted
        self.compliant_alternative = compliant_alternative


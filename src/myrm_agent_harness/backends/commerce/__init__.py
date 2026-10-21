"""Commerce backend interfaces.

[INPUT]
- .types::CommerceRole, Money, VariantOption, ProductVariant, Product, ProductFilter,
  CartLine, Cart, CartUpdateResult, OrderStatus, OrderLine, Order, PolicyCategory,
  Policy, PolicySearchResult, TopProductMetric, PerformanceSummary, ListingStatus,
  Listing, ChangeType, StagedChange, ApplyResult, CompetitorPrice, PricingContext,
  InventoryAlertSeverity, InventoryAlert, ShoppingSessionState, MerchantSessionState
- .protocols::StorefrontBackendProtocol, MerchantBackendProtocol

[OUTPUT]
- Public exports for dual-role commerce backend interfaces.

[POS]
Commerce backends entry point in myrm-agent-harness.
"""

from myrm_agent_harness.backends.commerce.protocols import (
    MerchantBackendProtocol,
    StorefrontBackendProtocol,
)
from myrm_agent_harness.backends.commerce.types import (
    ApplyResult,
    Cart,
    CartLine,
    CartUpdateResult,
    ChangeType,
    CommerceRole,
    CompetitorPrice,
    InventoryAlert,
    InventoryAlertSeverity,
    Listing,
    ListingStatus,
    MerchantSessionContext,
    MerchantSessionState,
    Money,
    Order,
    OrderLine,
    OrderStatus,
    PerformanceSummary,
    Policy,
    PolicyCategory,
    PolicySearchResult,
    PricingContext,
    Product,
    ProductFilter,
    ProductVariant,
    ShoppingSessionContext,
    ShoppingSessionState,
    StagedChange,
    TopProductMetric,
    VariantOption,
)

# Backward-compatibility alias
StorefrontBackend = StorefrontBackendProtocol
MerchantBackend = MerchantBackendProtocol

__all__ = [
    "ApplyResult",
    "Cart",
    "CartLine",
    "CartUpdateResult",
    "ChangeType",
    "CommerceRole",
    "CompetitorPrice",
    "InventoryAlert",
    "InventoryAlertSeverity",
    "Listing",
    "ListingStatus",
    "MerchantBackend",
    "MerchantBackendProtocol",
    "MerchantSessionContext",
    "MerchantSessionState",
    "Money",
    "Order",
    "OrderLine",
    "OrderStatus",
    "PerformanceSummary",
    "Policy",
    "PolicyCategory",
    "PolicySearchResult",
    "PricingContext",
    "Product",
    "ProductFilter",
    "ProductVariant",
    "ShoppingSessionContext",
    "ShoppingSessionState",
    "StagedChange",
    "StorefrontBackend",
    "StorefrontBackendProtocol",
    "TopProductMetric",
    "VariantOption",
]

"""Commerce backend protocols for Storefront (C-end) and Merchant (B-end).

[INPUT]
- .types::Product, ProductFilter, Cart, CartUpdateResult, Order, PolicySearchResult,
  PerformanceSummary, Listing, StagedChange, ApplyResult, PricingContext,
  InventoryAlert, VariantOption (POS: 商业领域 DTO 类型)
- .exceptions::CommerceError, Unavailable, NotOffered, InvalidStagedChange,
  ChangeNotApplicable (POS: 商业领域标准异常)

[OUTPUT]
- StorefrontBackendProtocol: C端导购与交易后端协议
- MerchantBackendProtocol: B端商家运营与库存后勤协议

[POS]
Dual-role commerce backend contracts in myrm-agent-harness.
Decouples agent loop and prompt orchestration from underlying e-commerce platforms.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from myrm_agent_harness.backends.commerce.types import (
    ApplyResult,
    Cart,
    CartUpdateResult,
    ChangeType,
    InventoryAlert,
    Listing,
    Order,
    PerformanceSummary,
    PolicySearchResult,
    PricingContext,
    Product,
    ProductFilter,
    StagedChange,
    VariantOption,
)


@runtime_checkable
class StorefrontBackendProtocol(Protocol):
    """Protocol for customer-facing storefront backends.

    Handles product discovery, variant interrogation, shopping cart mutation,
    customer order tracking, and store policy lookup.
    """

    async def search_products(
        self,
        query: str,
        *,
        filters: ProductFilter | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[Product]:
        """Search catalog products with optional filters.

        Args:
            query: Free-text search query.
            filters: Optional structured filter criteria.
            limit: Maximum items to return (capped to prevent context flooding).
            offset: Pagination offset.

        Returns:
            List of matching Product instances.
        """
        ...

    async def get_product_details(self, product_id: str) -> Product | None:
        """Retrieve full details of a single product including all variants.

        Args:
            product_id: The unique identifier of the product.

        Returns:
            Product instance if found, or None.
        """
        ...

    async def get_orders(
        self,
        customer_id: str,
        *,
        limit: int = 10,
    ) -> list[Order]:
        """Retrieve recent customer orders.

        Args:
            customer_id: Unique customer/account identifier.
            limit: Maximum number of orders to return.

        Returns:
            List of historical Order records.
        """
        ...

    async def search_policies(self, query: str) -> list[PolicySearchResult]:
        """Search store policies (shipping, returns, warranty, etc.).

        Args:
            query: Policy question or keyword.

        Returns:
            List of matching policy excerpts.
        """
        ...

    async def get_cart(self, session_id: str) -> Cart:
        """Get or initialize the current session shopping cart.

        Args:
            session_id: Active customer session id.

        Returns:
            Current Cart instance.
        """
        ...

    async def add_to_cart(
        self,
        session_id: str,
        product_id: str,
        *,
        quantity: int = 1,
        variant_id: str | None = None,
        selected_options: tuple[VariantOption, ...] = (),
    ) -> CartUpdateResult:
        """Add an item or variant to the session shopping cart.

        Args:
            session_id: Active customer session id.
            product_id: Target product identifier.
            quantity: Number of units to add (must be positive).
            variant_id: Specific variant id if product has options.
            selected_options: Selected variant options.

        Returns:
            CartUpdateResult containing the updated cart state.

        Raises:
            Unavailable: If the item or variant is out of stock.
            CommerceError: If options are required but not provided.
        """
        ...

    async def remove_from_cart(
        self,
        session_id: str,
        line_id: str,
    ) -> CartUpdateResult:
        """Remove a line from the shopping cart.

        Args:
            session_id: Active customer session id.
            line_id: Unique identifier of the cart line.

        Returns:
            CartUpdateResult containing the updated cart state.
        """
        ...

    async def update_cart_item(
        self,
        session_id: str,
        line_id: str,
        quantity: int,
    ) -> CartUpdateResult:
        """Update the quantity of an existing cart line.

        Args:
            session_id: Active customer session id.
            line_id: Unique identifier of the cart line.
            quantity: New quantity (if <= 0, line is removed).

        Returns:
            CartUpdateResult containing the updated cart state.
        """
        ...


@runtime_checkable
class MerchantBackendProtocol(Protocol):
    """Protocol for merchant back-office backends.

    Handles business performance analytics, product listing maintenance,
    two-phase staged proposal changes (staging and apply), pricing bounds,
    and inventory replenishment alerts.
    """

    async def get_performance_summary(
        self,
        time_range: str = "last_7d",
    ) -> PerformanceSummary:
        """Fetch store performance KPI summary for the specified period.

        Args:
            time_range: Window string (e.g. "today", "last_7d", "last_30d").

        Returns:
            PerformanceSummary aggregate metrics.
        """
        ...

    async def get_listing(self, listing_id: str) -> Listing | None:
        """Retrieve a specific merchant catalog listing.

        Args:
            listing_id: Listing unique identifier.

        Returns:
            Listing entity or None if not found.
        """
        ...

    async def stage_listing_change(
        self,
        listing_id: str,
        change_type: ChangeType,
        proposed_values: tuple[tuple[str, str], ...],
    ) -> StagedChange:
        """Stage a proposed change for human review or pre-apply validation.

        Args:
            listing_id: Target listing identifier.
            change_type: Category of the change.
            proposed_values: Key-value tuple of proposed attributes.

        Returns:
            Created StagedChange instance.

        Raises:
            ChangeNotApplicable: If the listing cannot accept the change.
        """
        ...

    async def apply_staged_change(self, change_id: str) -> ApplyResult:
        """Apply a previously staged change to the live store catalog.

        Args:
            change_id: Unique staged change proposal identifier.

        Returns:
            ApplyResult with audit tracking info.

        Raises:
            InvalidStagedChange: If the staged proposal does not exist or expired.
        """
        ...

    async def get_pricing_context(self, listing_id: str) -> PricingContext:
        """Retrieve margin, floor/ceiling bounds, and competitor prices.

        Args:
            listing_id: Listing unique identifier.

        Returns:
            PricingContext for guardrail validation and pricing decisions.
        """
        ...

    async def get_inventory_alerts(
        self,
        min_severity: str = "warning",
    ) -> list[InventoryAlert]:
        """Fetch inventory stockout warnings and reorder recommendations."""
        ...


# Aliases for compatibility
StorefrontBackend = StorefrontBackendProtocol
MerchantBackend = MerchantBackendProtocol




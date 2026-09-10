"""Unit tests for Commerce Backend Protocols, DTOs, and InMemory implementations."""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.commerce import (
    ApplyResult,
    Cart,
    CartLine,
    CartUpdateResult,
    ChangeNotApplicable,
    ChangeType,
    CommerceError,
    CommerceRole,
    InMemoryMerchantBackend,
    InMemoryStorefrontBackend,
    InvalidStagedChange,
    InventoryAlert,
    InventoryAlertSeverity,
    Listing,
    ListingStatus,
    MerchantBackendProtocol,
    Order,
    OrderStatus,
    PerformanceSummary,
    Policy,
    PolicyCategory,
    PolicySearchResult,
    PricingContext,
    Product,
    ProductFilter,
    ProductVariant,
    StorefrontBackendProtocol,
    Unavailable,
    VariantOption,
)


@pytest.fixture
def sample_catalog() -> list[Product]:
    return [
        Product(
            product_id="prod_runner_01",
            title="AeroStride Carbon Running Shoes",
            description="High-cushion marathon shoes with responsive carbon-fiber plate.",
            base_price=180.0,
            category="footwear",
            in_stock=True,
            tags=("running", "marathon", "lightweight"),
            variants=(
                ProductVariant(
                    variant_id="var_runner_red_42",
                    title="Red / EU 42",
                    price=180.0,
                    sku="AERO-RED-42",
                    in_stock=True,
                    inventory_quantity=15,
                    options=(
                        VariantOption(name="color", value="red"),
                        VariantOption(name="size", value="42"),
                    ),
                ),
                ProductVariant(
                    variant_id="var_runner_blue_43",
                    title="Blue / EU 43",
                    price=185.0,
                    sku="AERO-BLUE-43",
                    in_stock=False,
                    inventory_quantity=0,
                    options=(
                        VariantOption(name="color", value="blue"),
                        VariantOption(name="size", value="43"),
                    ),
                ),
            ),
        ),
        Product(
            product_id="prod_tee_01",
            title="Merino Trail Breathable T-Shirt",
            description="Ultra-fine 100% merino wool shirt for hiking and daily comfort.",
            base_price=65.0,
            category="apparel",
            in_stock=True,
            tags=("wool", "breathable", "outdoor"),
            variants=(),
        ),
        Product(
            product_id="prod_out_of_stock",
            title="Rare Heritage Cap",
            description="Limited edition cap currently out of stock.",
            base_price=45.0,
            category="apparel",
            in_stock=False,
            tags=("limited",),
            variants=(),
        ),
    ]


@pytest.fixture
def sample_policies() -> list[Policy]:
    return [
        Policy(
            policy_id="pol_returns",
            category=PolicyCategory.RETURNS,
            title="30-Day Hassle-Free Returns",
            content_markdown="Customers may return unworn items in original packaging within 30 days of delivery.",
        ),
        Policy(
            policy_id="pol_warranty",
            category=PolicyCategory.WARRANTY,
            title="1-Year Limited Hardware Warranty",
            content_markdown="All footwear components are covered against manufacturing defects for 12 months.",
        ),
    ]


class TestCommerceProtocolCompliance:
    """Validate that implementations satisfy @runtime_checkable Protocols."""

    def test_storefront_backend_protocol_check(self) -> None:
        backend = InMemoryStorefrontBackend()
        assert isinstance(backend, StorefrontBackendProtocol)

    def test_merchant_backend_protocol_check(self) -> None:
        backend = InMemoryMerchantBackend()
        assert isinstance(backend, MerchantBackendProtocol)


class TestStorefrontBackend:
    """Comprehensive test suite for StorefrontBackend operations."""

    @pytest.mark.asyncio
    async def test_search_and_filters(self, sample_catalog: list[Product]) -> None:
        backend = InMemoryStorefrontBackend(products=sample_catalog)

        # Keyword search
        res = await backend.search_products("running")
        assert len(res) == 1
        assert res[0].product_id == "prod_runner_01"

        # Category filter
        apparel_res = await backend.search_products(
            "", filters=ProductFilter(category="apparel")
        )
        assert len(apparel_res) == 2

        # In-stock only filter
        in_stock_res = await backend.search_products(
            "", filters=ProductFilter(category="apparel", in_stock_only=True)
        )
        assert len(in_stock_res) == 1
        assert in_stock_res[0].product_id == "prod_tee_01"

        # Price range filter
        price_res = await backend.search_products(
            "", filters=ProductFilter(min_price=100.0, max_price=200.0)
        )
        assert len(price_res) == 1
        assert price_res[0].product_id == "prod_runner_01"

    @pytest.mark.asyncio
    async def test_get_product_details(self, sample_catalog: list[Product]) -> None:
        backend = InMemoryStorefrontBackend(products=sample_catalog)

        details = await backend.get_product_details("prod_runner_01")
        assert details is not None
        assert len(details.variants) == 2
        assert details.variants[0].variant_id == "var_runner_red_42"

        missing = await backend.get_product_details("non_existent_id")
        assert missing is None

    @pytest.mark.asyncio
    async def test_cart_operations(self, sample_catalog: list[Product]) -> None:
        backend = InMemoryStorefrontBackend(products=sample_catalog)
        session_id = "test_sess_01"

        # Initial empty cart
        cart = await backend.get_cart(session_id)
        assert len(cart.lines) == 0
        assert cart.subtotal == 0.0

        # Add single item without variants
        result = await backend.add_to_cart(session_id, "prod_tee_01", quantity=2)
        assert result.action == "add"
        assert len(result.cart.lines) == 1
        line = result.cart.lines[0]
        assert line.quantity == 2
        assert line.unit_price == 65.0
        assert result.cart.subtotal == 130.0

        # Add variant item
        v_result = await backend.add_to_cart(
            session_id,
            "prod_runner_01",
            quantity=1,
            variant_id="var_runner_red_42",
        )
        assert len(v_result.cart.lines) == 2
        assert v_result.cart.subtotal == 130.0 + 180.0

        # Update cart item quantity
        line_id = line.line_id
        u_result = await backend.update_cart_item(session_id, line_id, quantity=3)
        assert u_result.action == "update"
        updated_line = next(l for l in u_result.cart.lines if l.line_id == line_id)
        assert updated_line.quantity == 3
        assert u_result.cart.subtotal == 195.0 + 180.0

        # Remove item from cart
        r_result = await backend.remove_from_cart(session_id, line_id)
        assert r_result.action == "remove"
        assert len(r_result.cart.lines) == 1
        assert r_result.cart.lines[0].product_id == "prod_runner_01"

    @pytest.mark.asyncio
    async def test_cart_exceptions(self, sample_catalog: list[Product]) -> None:
        backend = InMemoryStorefrontBackend(products=sample_catalog)
        session_id = "test_sess_errors"

        # Out of stock product
        with pytest.raises(Unavailable) as exc_info:
            await backend.add_to_cart(session_id, "prod_out_of_stock", quantity=1)
        assert exc_info.value.item_id == "prod_out_of_stock"

        # Multi-variant product without variant_id
        with pytest.raises(Unavailable) as exc_info:
            await backend.add_to_cart(session_id, "prod_runner_01", quantity=1)
        assert "requires selecting a variant" in str(exc_info.value)
        assert "var_runner_red_42" in exc_info.value.available_variant_ids

        # Out of stock variant
        with pytest.raises(Unavailable) as exc_info:
            await backend.add_to_cart(
                session_id,
                "prod_runner_01",
                quantity=1,
                variant_id="var_runner_blue_43",
            )
        assert "out of stock" in str(exc_info.value)

        # Invalid quantity
        with pytest.raises(ValueError):
            await backend.add_to_cart(session_id, "prod_tee_01", quantity=0)

    @pytest.mark.asyncio
    async def test_policies_and_orders(
        self, sample_policies: list[Policy]
    ) -> None:
        backend = InMemoryStorefrontBackend(policies=sample_policies)

        # Policy search
        hits = await backend.search_policies("returns")
        assert len(hits) >= 1
        assert hits[0].category == PolicyCategory.RETURNS
        assert hits[0].policy_id == "pol_returns"

        # Orders query
        orders = await backend.get_orders("cust_001")
        assert len(orders) >= 1
        assert orders[0].customer_id == "cust_001"


class TestMerchantBackend:
    """Comprehensive test suite for MerchantBackend operations."""

    @pytest.fixture
    def sample_listings(self) -> list[Listing]:
        return [
            Listing(
                listing_id="list_101",
                title="Bluetooth Speaker Pro",
                description="Portable waterproof speaker",
                price=89.99,
                inventory_count=45,
                status=ListingStatus.ACTIVE,
                category="audio",
                tags=("portable", "waterproof"),
            ),
            Listing(
                listing_id="list_102",
                title="Wireless Noise-Canceling Earbuds",
                description="In-ear earbuds with ANC",
                price=149.99,
                inventory_count=3,
                status=ListingStatus.ACTIVE,
                category="audio",
                tags=("anc", "audio"),
            ),
        ]

    @pytest.mark.asyncio
    async def test_performance_summary_and_listing(
        self, sample_listings: list[Listing]
    ) -> None:
        backend = InMemoryMerchantBackend(listings=sample_listings)

        summary = await backend.get_performance_summary("last_7d")
        assert summary.gmv > 0
        assert summary.order_count > 0
        assert summary.conversion_rate > 0

        listing = await backend.get_listing("list_101")
        assert listing is not None
        assert listing.title == "Bluetooth Speaker Pro"
        assert listing.price == 89.99

        missing = await backend.get_listing("non_existent")
        assert missing is None

    @pytest.mark.asyncio
    async def test_two_phase_staging_and_apply(
        self, sample_listings: list[Listing]
    ) -> None:
        backend = InMemoryMerchantBackend(listings=sample_listings)

        # Stage a price change
        staged = await backend.stage_listing_change(
            listing_id="list_101",
            change_type=ChangeType.PRICE_UPDATE,
            proposed_values=(("price", "99.99"),),
        )
        assert staged.change_id.startswith("stg_")
        assert staged.applied is False

        # Apply the staged change
        result = await backend.apply_staged_change(staged.change_id)
        assert result.success is True
        assert result.listing_id == "list_101"

        # Verify live listing was updated
        updated_listing = await backend.get_listing("list_101")
        assert updated_listing is not None
        assert updated_listing.price == 99.99

        # Applying a second time raises InvalidStagedChange
        with pytest.raises(InvalidStagedChange):
            await backend.apply_staged_change(staged.change_id)

    @pytest.mark.asyncio
    async def test_staging_guardrails_exceptions(
        self, sample_listings: list[Listing]
    ) -> None:
        backend = InMemoryMerchantBackend(listings=sample_listings)

        # Staging for a non-existent listing
        with pytest.raises(ChangeNotApplicable):
            await backend.stage_listing_change(
                listing_id="non_existent",
                change_type=ChangeType.PRICE_UPDATE,
                proposed_values=(("price", "50.0"),),
            )

        # Applying a non-existent staged change
        with pytest.raises(InvalidStagedChange):
            await backend.apply_staged_change("stg_missing_123")

    @pytest.mark.asyncio
    async def test_pricing_context_and_inventory_alerts(
        self, sample_listings: list[Listing]
    ) -> None:
        backend = InMemoryMerchantBackend(listings=sample_listings)

        # Pricing context
        ctx = await backend.get_pricing_context("list_101")
        assert ctx.current_price == 89.99
        assert ctx.min_allowed_price < ctx.current_price < ctx.max_allowed_price

        # Inventory alerts
        alerts = await backend.get_inventory_alerts(min_severity="warning")
        assert isinstance(alerts, list)
        for alert in alerts:
            assert alert.severity in {InventoryAlertSeverity.WARNING, InventoryAlertSeverity.CRITICAL}

"""Tests for commerce backend protocols, data models, exceptions, and in-memory implementations.

[INPUT]
- myrm_agent_harness.backends.commerce::*
- myrm_agent_harness.api.protocols::StorefrontBackend, MerchantBackend

[OUTPUT]
- Unit tests validating StorefrontBackend and MerchantBackend contracts, edge cases, and in-memory behaviors.

[POS]
Unit tests for commerce backend domain contracts and implementations.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.api.protocols import MerchantBackend, StorefrontBackend
from myrm_agent_harness.backends.commerce.exceptions import (
    ChangeNotApplicable,
    CommerceError,
    InvalidStagedChange,
    NotOffered,
    Unavailable,
)
from myrm_agent_harness.backends.commerce.memory_backend import (
    InMemoryMerchantBackend,
    InMemoryStorefrontBackend,
)
from myrm_agent_harness.backends.commerce.types import (
    Cart,
    CartLine,
    ChangeType,
    Listing,
    ListingStatus,
    Order,
    OrderStatus,
    PerformanceSummary,
    Policy,
    PolicyCategory,
    Product,
    ProductFilter,
    ProductVariant,
    StagedChange,
    VariantOption,
)


@pytest.fixture
def sample_catalog() -> list[Product]:
    variant_1 = ProductVariant(
        variant_id="var_shoe_red_42",
        title="Running Shoe - Red / 42",
        price=129.0,
        options=(VariantOption("color", "Red"), VariantOption("size", "42")),
        inventory_quantity=15,
        in_stock=True,
    )
    variant_2 = ProductVariant(
        variant_id="var_shoe_blue_42",
        title="Running Shoe - Blue / 42",
        price=129.0,
        options=(VariantOption("color", "Blue"), VariantOption("size", "42")),
        inventory_quantity=0,
        in_stock=False,
    )
    product_1 = Product(
        product_id="prod_shoe_001",
        title="Pro Runner 2026",
        description="High performance lightweight running shoes with mesh breathability.",
        base_price=129.0,
        category="Footwear",
        tags=("running", "sports", "footwear"),
        variants=(variant_1, variant_2),
        in_stock=True,
    )
    product_2 = Product(
        product_id="prod_socks_001",
        title="Cotton Sports Socks 3-Pack",
        description="Comfortable pure cotton sweat-absorbing socks.",
        base_price=15.0,
        category="Apparel",
        tags=("socks", "cotton"),
        variants=(),
        in_stock=True,
    )
    return [product_1, product_2]


@pytest.fixture
def sample_policies() -> list[Policy]:
    return [
        Policy(
            policy_id="pol_return_30d",
            title="30-Day Return Guarantee",
            category=PolicyCategory.RETURNS,
            content_markdown="Unopened items can be returned within 30 days of receipt.",
        ),
        Policy(
            policy_id="pol_free_shipping",
            title="Standard Free Shipping",
            category=PolicyCategory.SHIPPING,
            content_markdown="Free shipping on orders over $50.",
        ),
    ]


@pytest.mark.asyncio
async def test_storefront_conforms_to_protocol(
    sample_catalog: list[Product],
    sample_policies: list[Policy],
) -> None:
    backend: StorefrontBackend = InMemoryStorefrontBackend(
        products=sample_catalog,
        policies=sample_policies,
    )

    # 1. Product Search
    results = await backend.search_products(query="runner")
    assert len(results) == 1
    assert results[0].product_id == "prod_shoe_001"
    assert results[0].title == "Pro Runner 2026"

    # Search with category filter
    cat_results = await backend.search_products(
        query="",
        filters=ProductFilter(category="Apparel"),
    )
    assert len(cat_results) == 1
    assert cat_results[0].product_id == "prod_socks_001"

    # 2. Get Product Details
    details = await backend.get_product_details("prod_shoe_001")
    assert details is not None
    assert len(details.variants) == 2
    assert details.variants[0].variant_id == "var_shoe_red_42"

    # Missing product returns None
    missing = await backend.get_product_details("prod_missing")
    assert missing is None

    # 3. Policies search
    policy_results = await backend.search_policies(query="return")
    assert len(policy_results) == 1
    assert policy_results[0].policy_id == "pol_return_30d"

    # 4. Cart Operations
    session_id = "sess_shopper_001"
    cart_empty = await backend.get_cart(session_id)
    assert cart_empty.lines == ()
    assert cart_empty.subtotal == 0.0

    # Add available variant to cart
    res = await backend.add_to_cart(
        session_id=session_id,
        product_id="prod_shoe_001",
        variant_id="var_shoe_red_42",
        quantity=2,
    )
    cart_updated = res.cart
    assert len(cart_updated.lines) == 1
    assert cart_updated.lines[0].variant_id == "var_shoe_red_42"
    assert cart_updated.lines[0].quantity == 2
    assert cart_updated.subtotal == 258.0

    # Attempt to add unavailable variant -> Unavailable exception
    with pytest.raises(Unavailable) as exc_info:
        await backend.add_to_cart(
            session_id=session_id,
            product_id="prod_shoe_001",
            variant_id="var_shoe_blue_42",
            quantity=1,
        )
    assert exc_info.value.item_id == "var_shoe_blue_42"
    assert exc_info.value.code == "UNAVAILABLE"

    # Attempt to add non-existent product -> Unavailable exception
    with pytest.raises(Unavailable):
        await backend.add_to_cart(
            session_id=session_id,
            product_id="prod_unknown_999",
            quantity=1,
        )


@pytest.mark.asyncio
async def test_merchant_conforms_to_protocol(
    sample_catalog: list[Product],
) -> None:
    listings = [
        Listing(
            listing_id=p.product_id,
            title=p.title,
            description=p.description,
            price=p.base_price,
            inventory_count=100 if p.in_stock else 0,
            status=ListingStatus.ACTIVE,
            category=p.category,
            tags=p.tags,
        )
        for p in sample_catalog
    ]
    backend: MerchantBackend = InMemoryMerchantBackend(listings=listings)

    # 1. Business performance summary
    summary = await backend.get_performance_summary(time_range="last_7d")
    assert isinstance(summary, PerformanceSummary)
    assert summary.total_sales > 0

    # 2. Get listing
    listing = await backend.get_listing("prod_shoe_001")
    assert listing is not None
    assert listing.title == "Pro Runner 2026"

    # 3. Two-phase listing modification: Stage -> Apply
    staged = await backend.stage_listing_change(
        listing_id="prod_shoe_001",
        change_type=ChangeType.PRICE_UPDATE,
        proposed_values=(("price", "119.0"), ("title", "Pro Runner 2026 (Promo)")),
    )
    assert staged.change_id.startswith("stg_")
    assert not staged.applied

    # Apply staged change
    apply_res = await backend.apply_staged_change(staged.change_id)
    assert apply_res.success
    assert apply_res.listing_id == "prod_shoe_001"

    # Verify updated listing
    updated_listing = await backend.get_listing("prod_shoe_001")
    assert updated_listing is not None
    assert updated_listing.price == 119.0
    assert updated_listing.title == "Pro Runner 2026 (Promo)"

    # Cannot apply already applied change
    with pytest.raises(InvalidStagedChange):
        await backend.apply_staged_change(staged.change_id)


@pytest.mark.asyncio
async def test_merchant_invalid_stage_target() -> None:
    backend = InMemoryMerchantBackend(listings=[])

    with pytest.raises(ChangeNotApplicable) as exc_info:
        await backend.stage_listing_change(
            listing_id="prod_non_existent",
            change_type=ChangeType.PRICE_UPDATE,
            proposed_values=(("price", "99.0"),),
        )
    assert exc_info.value.code == "CHANGE_NOT_APPLICABLE"


def test_commerce_exceptions_representation() -> None:
    not_offered = NotOffered("Delivery to this postal code is not offered.")
    assert not_offered.code == "NOT_OFFERED"
    assert "postal code" in str(not_offered)

    unavailable = Unavailable(
        "Out of stock",
        item_id="var_red_42",
        available_variant_ids=["var_black_42"],
    )
    assert unavailable.item_id == "var_red_42"
    assert unavailable.available_variant_ids == ["var_black_42"]
    assert unavailable.code == "UNAVAILABLE"

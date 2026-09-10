"""Tests for Quad-Vertical Commerce Starter Packs (Retail, Travel, Telecom, Entertainment).

Verifies:
1. Turnkey factory and domain resolution for all four industry verticals.
2. Domain-specific catalog, variants, options, and business policies sanity.
3. Dual-role runtime integration (Storefront discovery, option filtering, cart writes; Merchant KPI & listings).
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.commerce.memory_backend import (
    InMemoryMerchantBackend,
    InMemoryStorefrontBackend,
)
from myrm_agent_harness.backends.commerce.types import (
    PolicyCategory,
    ProductFilter,
    ShoppingSessionState,
)
from myrm_agent_harness.backends.commerce.verticals import (
    CommerceStarterPack,
    VerticalDomain,
    create_entertainment_starter_pack,
    create_retail_starter_pack,
    create_telecom_starter_pack,
    create_travel_starter_pack,
    get_vertical_starter_pack,
)


def test_vertical_factory_dispatch() -> None:
    """Test get_vertical_starter_pack dispatches correctly for all valid domains."""
    domains: list[VerticalDomain] = ["retail", "travel", "telecom", "entertainment"]
    for domain in domains:
        pack = get_vertical_starter_pack(domain)
        assert isinstance(pack, CommerceStarterPack)
        assert pack.domain == domain
        assert isinstance(pack.storefront_backend, InMemoryStorefrontBackend)
        assert isinstance(pack.merchant_backend, InMemoryMerchantBackend)

    with pytest.raises(ValueError, match="Unknown commerce vertical domain"):
        get_vertical_starter_pack("automotive")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_retail_starter_pack_flow() -> None:
    """Test fast-moving consumer retail pack: shoes with color/size variants and headphones."""
    pack = create_retail_starter_pack()
    assert pack.domain == "retail"
    storefront = pack.storefront_backend
    merchant = pack.merchant_backend

    # 1. Product Search & Filter
    products = await storefront.search_products(query="marathon")
    assert len(products) == 1
    shoe = products[0]
    assert shoe.product_id == "ret_shoe_001"
    assert len(shoe.variants) == 3

    # Category filter
    audio_items = await storefront.search_products(
        query="",
        filters=ProductFilter(category="electronics"),
    )
    assert len(audio_items) == 1
    assert audio_items[0].product_id == "ret_headphone_002"

    # 2. Product Details
    details = await storefront.get_product_details("ret_shoe_001")
    assert details is not None
    assert details.base_price == 180.0

    # 3. Add to Cart: in-stock variant
    session_id = "sess_shopper_retail"
    cart_res = await storefront.add_to_cart(
        session_id=session_id,
        product_id="ret_shoe_001",
        variant_id="ret_shoe_001_red_42",
        quantity=2,
    )
    assert cart_res.action == "add"
    assert len(cart_res.cart.lines) == 1
    assert cart_res.cart.lines[0].quantity == 2
    assert cart_res.cart.subtotal == 360.0

    # 4. Policies
    policies = await storefront.search_policies(query="return")
    assert len(policies) >= 1
    assert any(p.category == PolicyCategory.RETURNS for p in policies)

    # 5. Merchant Listing inspection
    listing = await merchant.get_listing("list_ret_001")
    assert listing is not None
    assert listing.price == 180.0
    assert listing.inventory_count == 43


@pytest.mark.asyncio
async def test_travel_starter_pack_flow() -> None:
    """Test travel & hospitality pack: seaside resort rooms and activity tour packages."""
    pack = create_travel_starter_pack()
    assert pack.domain == "travel"
    storefront = pack.storefront_backend
    merchant = pack.merchant_backend

    # 1. Search Resort and Activity
    all_travel = await storefront.search_products(query="")
    assert len(all_travel) == 2

    # Search Lodging
    resorts = await storefront.search_products(
        query="resort",
        filters=ProductFilter(category="lodging"),
    )
    assert len(resorts) == 1
    resort = resorts[0]
    assert resort.product_id == "trv_hotel_grand_seaside"
    assert len(resort.variants) == 2

    # 2. Room Options
    variant_ids = [v.variant_id for v in resort.variants]
    assert "trv_room_deluxe_ocean" in variant_ids
    assert "trv_room_exec_suite" in variant_ids

    # 3. Book Activity
    session_id = "sess_traveler_01"
    cart_res = await storefront.add_to_cart(
        session_id=session_id,
        product_id="trv_pkg_island_hopping",
        quantity=3,
    )
    assert cart_res.action == "add"
    assert cart_res.cart.subtotal == 95.0 * 3

    # 4. Cancellation Policy Check
    canc_policies = await storefront.search_policies(query="cancellation")
    assert len(canc_policies) >= 1
    assert "48 hours" in canc_policies[0].excerpt

    # 5. Merchant performance summary
    summary = await merchant.get_performance_summary()
    assert summary.gmv > 0


@pytest.mark.asyncio
async def test_telecom_starter_pack_flow() -> None:
    """Test telecommunications pack: 5G mobile service plans and roaming data bundles."""
    pack = create_telecom_starter_pack()
    assert pack.domain == "telecom"
    storefront = pack.storefront_backend
    merchant = pack.merchant_backend

    # 1. Search Plans
    plans = await storefront.search_products(query="5g")
    assert len(plans) >= 1
    mobile_plan = plans[0]
    assert mobile_plan.product_id == "tel_plan_infinite_5g"
    assert len(mobile_plan.variants) == 2

    # Term variants: monthly vs annual discount
    monthly_var = next(v for v in mobile_plan.variants if v.variant_id == "tel_plan_infinite_1line")
    annual_var = next(v for v in mobile_plan.variants if v.variant_id == "tel_plan_infinite_annual")
    assert monthly_var.price == 65.0
    assert annual_var.price == 55.25

    # 2. Add annual plan and roaming pass to cart
    session_id = "sess_subscriber_01"
    await storefront.add_to_cart(
        session_id=session_id,
        product_id="tel_plan_infinite_5g",
        variant_id="tel_plan_infinite_annual",
        quantity=1,
    )
    cart_res = await storefront.add_to_cart(
        session_id=session_id,
        product_id="tel_roaming_asia_pack",
        quantity=1,
    )
    assert len(cart_res.cart.lines) == 2
    assert cart_res.cart.subtotal == 55.25 + 35.0

    # 3. Policy & Fair usage terms
    terms = await storefront.search_policies(query="fair usage")
    assert len(terms) >= 1
    assert "100GB" in terms[0].excerpt

    # 4. Merchant listing
    listing = await merchant.get_listing("list_tel_001")
    assert listing is not None
    assert listing.price == 65.0


@pytest.mark.asyncio
async def test_entertainment_starter_pack_flow() -> None:
    """Test entertainment & live events pack: festival tiers and non-refundable tickets."""
    pack = create_entertainment_starter_pack()
    assert pack.domain == "entertainment"
    storefront = pack.storefront_backend
    merchant = pack.merchant_backend

    # 1. Search Event Tickets
    events = await storefront.search_products(query="soundwave")
    assert len(events) == 1
    event = events[0]
    assert event.product_id == "ent_fest_soundwave_2026"
    assert len(event.variants) == 2

    # VIP vs GA tiers
    ga_tkt = next(v for v in event.variants if v.variant_id == "ent_tkt_ga_tier1")
    vip_tkt = next(v for v in event.variants if v.variant_id == "ent_tkt_vip_front")
    assert ga_tkt.price == 199.0
    assert vip_tkt.price == 399.0

    # 2. Add VIP Ticket to Cart
    session_id = "sess_festival_goer"
    cart_res = await storefront.add_to_cart(
        session_id=session_id,
        product_id="ent_fest_soundwave_2026",
        variant_id="ent_tkt_vip_front",
        quantity=2,
    )
    assert cart_res.cart.subtotal == 399.0 * 2

    # 3. Ticket Policies (Non-refundable + Real-name verification)
    policies = await storefront.search_policies(query="ticket")
    assert len(policies) >= 1
    assert "non-refundable" in policies[0].excerpt.lower()

    # 4. Merchant listing
    listing = await merchant.get_listing("list_ent_001")
    assert listing is not None
    assert listing.price == 199.0

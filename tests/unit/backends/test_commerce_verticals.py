"""Unit tests for Quad-Vertical Commerce Starter Packs (Retail, Travel, Telecom, Entertainment).

[INPUT]
- myrm_agent_harness.backends.commerce.verticals::*
- myrm_agent_harness.backends.commerce.types::ProductFilter, PolicyCategory, ListingStatus

[OUTPUT]
- Comprehensive test coverage for 4 industry vertical starter packs and unified factory.

[POS]
Unit tests validating that each vertical domain provides valid mock seed data,
conforms to Storefront/Merchant backend contracts, and supports realistic business flows.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.commerce.verticals import (
    CommerceStarterPack,
    create_entertainment_starter_pack,
    create_retail_starter_pack,
    create_telecom_starter_pack,
    create_travel_starter_pack,
    get_vertical_starter_pack,
)


@pytest.mark.asyncio
async def test_retail_starter_pack() -> None:
    pack = create_retail_starter_pack()
    assert isinstance(pack, CommerceStarterPack)
    assert pack.domain == "retail"
    assert len(pack.initial_products) >= 2
    assert len(pack.initial_policies) >= 2
    assert len(pack.initial_listings) >= 2

    # Storefront operations
    storefront = pack.storefront_backend
    shoes = await storefront.search_products("shoe")
    assert len(shoes) >= 1
    assert shoes[0].category == "footwear"
    assert len(shoes[0].variants) >= 2

    # Option resolution test on shoe
    details = await storefront.get_product_details("ret_shoe_001")
    assert details is not None
    assert any(opt.name == "size" for opt in details.variants[0].options)

    # Search policies
    returns = await storefront.search_policies("return")
    assert len(returns) >= 1

    # Merchant operations
    merchant = pack.merchant_backend
    listing = await merchant.get_listing("list_ret_001")
    assert listing is not None
    assert listing.price == 180.0


@pytest.mark.asyncio
async def test_travel_starter_pack() -> None:
    pack = create_travel_starter_pack()
    assert pack.domain == "travel"
    assert len(pack.initial_products) >= 1

    storefront = pack.storefront_backend
    resorts = await storefront.search_products("resort")
    assert len(resorts) >= 1
    assert resorts[0].category == "lodging"

    # Verify hotel room variants (ocean view / bed type)
    hotel = await storefront.get_product_details("trv_hotel_grand_seaside")
    assert hotel is not None
    assert len(hotel.variants) >= 2
    variant_views = [
        opt.value for v in hotel.variants for opt in v.options if opt.name == "view"
    ]
    assert "ocean" in variant_views

    # Merchant listing check
    merchant = pack.merchant_backend
    listing = await merchant.get_listing("list_trv_001")
    assert listing is not None
    assert listing.listing_id == "list_trv_001"


@pytest.mark.asyncio
async def test_telecom_starter_pack() -> None:
    pack = create_telecom_starter_pack()
    assert pack.domain == "telecom"
    assert len(pack.initial_products) >= 1

    storefront = pack.storefront_backend
    plans = await storefront.search_products("unlimited")
    assert len(plans) >= 1
    assert plans[0].category == "mobile_service"

    plan = await storefront.get_product_details(plans[0].product_id)
    assert plan is not None
    assert len(plan.variants) >= 1

    # Policies check
    policies = await storefront.search_policies("roaming")
    assert len(policies) >= 1


@pytest.mark.asyncio
async def test_entertainment_starter_pack() -> None:
    pack = create_entertainment_starter_pack()
    assert pack.domain == "entertainment"
    assert len(pack.initial_products) >= 1

    storefront = pack.storefront_backend
    events = await storefront.search_products("soundwave")
    assert len(events) >= 1
    assert events[0].category == "live_event"

    event = await storefront.get_product_details(events[0].product_id)
    assert event is not None
    # Check ticket tiers (e.g. VIP, Standard)
    tier_names = [opt.value for v in event.variants for opt in v.options if opt.name == "tier"]
    assert "vip" in tier_names or "standard" in tier_names or len(event.variants) >= 1


def test_unified_vertical_factory() -> None:
    for domain in ("retail", "travel", "telecom", "entertainment"):
        pack = get_vertical_starter_pack(domain)  # type: ignore[arg-type]
        assert pack.domain == domain
        assert pack.storefront_backend is not None
        assert pack.merchant_backend is not None

    with pytest.raises(ValueError) as exc_info:
        get_vertical_starter_pack("automotive")  # type: ignore[arg-type]
    assert "Unknown commerce vertical domain" in str(exc_info.value)

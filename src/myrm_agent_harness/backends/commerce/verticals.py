"""Quad-Vertical Commerce Starter Packs (Retail, Travel, Telecom, Entertainment).

[INPUT]
- typing::Literal
- pydantic::BaseModel, Field
- myrm_agent_harness.backends.commerce.types::Product, ProductVariant, VariantOption, Policy, PolicyCategory, Listing, ListingStatus
- myrm_agent_harness.backends.commerce.memory_backend::InMemoryStorefrontBackend, InMemoryMerchantBackend

[OUTPUT]
- VerticalDomain: 垂直行业枚举 ("retail" | "travel" | "telecom" | "entertainment")
- CommerceStarterPack: 包含行业双端 Backend、种子商品、刊登清单与核心业务策略的聚合包
- create_retail_starter_pack(): 生成标准零售行业启动包
- create_travel_starter_pack(): 生成酒店与旅行度假启动包
- create_telecom_starter_pack(): 生成电信流量与合约资费启动包
- create_entertainment_starter_pack(): 生成演出票务与赛事娱乐启动包
- get_vertical_starter_pack(): 统一工厂入口

[POS]
Out-of-the-box vertical industry reference packs providing standardized domains,
realistic mock catalogs, and zero-config in-memory dual-role runtimes.
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

from myrm_agent_harness.backends.commerce.memory_backend import (
    InMemoryMerchantBackend,
    InMemoryStorefrontBackend,
)
from myrm_agent_harness.backends.commerce.types import (
    Listing,
    ListingStatus,
    Policy,
    PolicyCategory,
    Product,
    ProductVariant,
    VariantOption,
)

VerticalDomain = Literal["retail", "travel", "telecom", "entertainment"]


class CommerceStarterPack(BaseModel):
    """Encapsulates storefront and merchant backends populated with domain-specific seed data."""

    domain: VerticalDomain
    display_name: str
    description: str
    storefront_backend: InMemoryStorefrontBackend
    merchant_backend: InMemoryMerchantBackend
    initial_products: list[Product] = Field(default_factory=list)
    initial_policies: list[Policy] = Field(default_factory=list)
    initial_listings: list[Listing] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


def create_retail_starter_pack() -> CommerceStarterPack:
    """Create Starter Pack for Retail (Apparel, Footwear, Consumer Electronics)."""
    products = [
        Product(
            product_id="ret_shoe_001",
            title="AeroStride Marathon Carbon Running Shoe",
            description="Ultra-responsive marathon racing shoe with carbon plate and zoom foam.",
            base_price=180.0,
            category="footwear",
            in_stock=True,
            tags=("retail", "footwear", "running", "marathon"),
            variants=(
                ProductVariant(
                    variant_id="ret_shoe_001_red_42",
                    title="Racing Red / EU 42",
                    price=180.0,
                    sku="AERO-RED-42",
                    in_stock=True,
                    inventory_quantity=25,
                    options=(
                        VariantOption(name="color", value="red"),
                        VariantOption(name="size", value="42"),
                    ),
                ),
                ProductVariant(
                    variant_id="ret_shoe_001_blk_42",
                    title="Stealth Black / EU 42",
                    price=180.0,
                    sku="AERO-BLK-42",
                    in_stock=True,
                    inventory_quantity=18,
                    options=(
                        VariantOption(name="color", value="black"),
                        VariantOption(name="size", value="42"),
                    ),
                ),
                ProductVariant(
                    variant_id="ret_shoe_001_red_43",
                    title="Racing Red / EU 43",
                    price=180.0,
                    sku="AERO-RED-43",
                    in_stock=False,
                    inventory_quantity=0,
                    options=(
                        VariantOption(name="color", value="red"),
                        VariantOption(name="size", value="43"),
                    ),
                ),
            ),
        ),
        Product(
            product_id="ret_headphone_002",
            title="AcousticPro Wireless Noise-Cancelling Headphones",
            description="Active noise cancellation headphones with 40-hour battery life and spatial audio.",
            base_price=249.0,
            category="electronics",
            in_stock=True,
            tags=("retail", "electronics", "audio", "bluetooth"),
            variants=(),
        ),
    ]

    policies = [
        Policy(
            policy_id="ret_pol_return",
            category=PolicyCategory.RETURNS,
            title="30-Day Hassle-Free Return Policy",
            content_markdown="Returns accepted within 30 days of delivery in original condition and packaging. Free return shipping for VIP members.",
        ),
        Policy(
            policy_id="ret_pol_shipping",
            category=PolicyCategory.SHIPPING,
            title="Standard & Expedited Shipping Rates",
            content_markdown="Free standard delivery on orders over $50 (3-5 business days). Express next-day shipping available for $15.",
        ),
    ]

    listings = [
        Listing(
            listing_id="list_ret_001",
            title=products[0].title,
            description=products[0].description,
            price=products[0].base_price,
            inventory_count=43,
            status=ListingStatus.ACTIVE,
            category=products[0].category,
            tags=products[0].tags,
        ),
        Listing(
            listing_id="list_ret_002",
            title=products[1].title,
            description=products[1].description,
            price=products[1].base_price,
            inventory_count=50,
            status=ListingStatus.ACTIVE,
            category=products[1].category,
            tags=products[1].tags,
        ),
    ]

    storefront = InMemoryStorefrontBackend(products=products, policies=policies)
    merchant = InMemoryMerchantBackend(listings=listings)

    return CommerceStarterPack(
        domain="retail",
        display_name="Fast-Moving Consumer Retail Starter Pack",
        description="Out-of-the-box apparel, footwear, and consumer electronics with variant options and standard returns.",
        storefront_backend=storefront,
        merchant_backend=merchant,
        initial_products=products,
        initial_policies=policies,
        initial_listings=listings,
    )


def create_travel_starter_pack() -> CommerceStarterPack:
    """Create Starter Pack for Travel & Hospitality (Hotels, Flight Packages, Resort Bookings)."""
    products = [
        Product(
            product_id="trv_hotel_grand_seaside",
            title="Grand Azure Seaside Resort & Spa",
            description="5-Star oceanfront luxury resort located in Riviera with infinity pool and private beach access.",
            base_price=320.0,
            category="lodging",
            in_stock=True,
            tags=("travel", "hotel", "resort", "oceanfront", "luxury"),
            variants=(
                ProductVariant(
                    variant_id="trv_room_deluxe_ocean",
                    title="Deluxe Ocean View King",
                    price=320.0,
                    sku="ROOM-DLX-OCN",
                    in_stock=True,
                    inventory_quantity=12,
                    options=(
                        VariantOption(name="view", value="ocean"),
                        VariantOption(name="bed", value="king"),
                    ),
                ),
                ProductVariant(
                    variant_id="trv_room_exec_suite",
                    title="Executive Panoramic Sea Suite",
                    price=580.0,
                    sku="ROOM-EXEC-PAN",
                    in_stock=True,
                    inventory_quantity=4,
                    options=(
                        VariantOption(name="view", value="panoramic"),
                        VariantOption(name="bed", value="king"),
                    ),
                ),
            ),
        ),
        Product(
            product_id="trv_pkg_island_hopping",
            title="Full-Day Speedboat Island Hopping & Snorkeling",
            description="Guided archipelago excursion including snorkel gear, seafood lunch, and national park fee.",
            base_price=95.0,
            category="activities",
            in_stock=True,
            tags=("travel", "tour", "island", "snorkeling"),
            variants=(),
        ),
    ]

    policies = [
        Policy(
            policy_id="trv_pol_cancellation",
            category=PolicyCategory.CANCELLATIONS,
            title="Flexible Hotel Cancellation Policy",
            content_markdown="Free cancellation up to 48 hours before standard 3:00 PM check-in date. Late cancellations charged 1 night stay.",
        ),
        Policy(
            policy_id="trv_pol_guarantee",
            category=PolicyCategory.WARRANTY,
            title="Weather Guarantee & Bad Weather Reschedule",
            content_markdown="Water activities cancelled due to weather warnings qualify for 100% refund or free date adjustment.",
        ),
    ]

    listings = [
        Listing(
            listing_id="list_trv_001",
            title=products[0].title,
            description=products[0].description,
            price=products[0].base_price,
            inventory_count=16,
            status=ListingStatus.ACTIVE,
            category=products[0].category,
            tags=products[0].tags,
        ),
        Listing(
            listing_id="list_trv_002",
            title=products[1].title,
            description=products[1].description,
            price=products[1].base_price,
            inventory_count=25,
            status=ListingStatus.ACTIVE,
            category=products[1].category,
            tags=products[1].tags,
        ),
    ]

    storefront = InMemoryStorefrontBackend(products=products, policies=policies)
    merchant = InMemoryMerchantBackend(listings=listings)

    return CommerceStarterPack(
        domain="travel",
        display_name="Travel & Hospitality Booking Starter Pack",
        description="Resort lodging, room view options, activities packages, and flexible check-in cancellation policies.",
        storefront_backend=storefront,
        merchant_backend=merchant,
        initial_products=products,
        initial_policies=policies,
        initial_listings=listings,
    )


def create_telecom_starter_pack() -> CommerceStarterPack:
    """Create Starter Pack for Telecommunications (5G Mobile Plans, Fiber Broadband, Roaming Bundles)."""
    products = [
        Product(
            product_id="tel_plan_infinite_5g",
            title="Unlimited Max 5G Mobile Service Plan",
            description="Unlimited high-speed 5G mobile data, unlimited domestic talk/text, and 20GB mobile hotspot.",
            base_price=65.0,
            category="mobile_service",
            in_stock=True,
            tags=("telecom", "5g", "mobile", "unlimited"),
            variants=(
                ProductVariant(
                    variant_id="tel_plan_infinite_1line",
                    title="1 Active Line / Monthly",
                    price=65.0,
                    sku="TEL-5G-1L",
                    in_stock=True,
                    inventory_quantity=999,
                    options=(VariantOption(name="contract_term", value="monthly"),),
                ),
                ProductVariant(
                    variant_id="tel_plan_infinite_annual",
                    title="1 Active Line / Annual Contract (15% Off)",
                    price=55.25,
                    sku="TEL-5G-ANNUAL",
                    in_stock=True,
                    inventory_quantity=999,
                    options=(VariantOption(name="contract_term", value="annual"),),
                ),
            ),
        ),
        Product(
            product_id="tel_roaming_asia_pack",
            title="Global Roaming Pass - Asia Pacific 15-Day Pass",
            description="15 days of unlimited data roaming in 18 Asia-Pacific countries with high-speed 4G/5G daily cap.",
            base_price=35.0,
            category="add_on",
            in_stock=True,
            tags=("telecom", "roaming", "travel_data"),
            variants=(),
        ),
    ]

    policies = [
        Policy(
            policy_id="tel_pol_billing",
            category=PolicyCategory.PAYMENT,
            title="Monthly Recurring Billing & Early Termination Terms",
            content_markdown="Monthly plans renew automatically on the 1st of each calendar month. Annual contracts incur a $50 early break fee.",
        ),
        Policy(
            policy_id="tel_pol_fair_usage",
            category=PolicyCategory.TERMS,
            title="Network Fair Usage and Traffic Management Policy",
            content_markdown="Data speeds may temporarily throttle during peak congestion periods after 100GB monthly high-speed consumption.",
        ),
        Policy(
            policy_id="tel_pol_roaming",
            category=PolicyCategory.TERMS,
            title="Global Roaming Terms and Daily Usage Caps",
            content_markdown="International roaming packages activate upon first network connection abroad. Daily speed throttles after 2GB high-speed usage.",
        ),
    ]

    listings = [
        Listing(
            listing_id="list_tel_001",
            title=products[0].title,
            description=products[0].description,
            price=products[0].base_price,
            inventory_count=999,
            status=ListingStatus.ACTIVE,
            category=products[0].category,
            tags=products[0].tags,
        ),
        Listing(
            listing_id="list_tel_002",
            title=products[1].title,
            description=products[1].description,
            price=products[1].base_price,
            inventory_count=999,
            status=ListingStatus.ACTIVE,
            category=products[1].category,
            tags=products[1].tags,
        ),
    ]

    storefront = InMemoryStorefrontBackend(products=products, policies=policies)
    merchant = InMemoryMerchantBackend(listings=listings)

    return CommerceStarterPack(
        domain="telecom",
        display_name="Telecommunications & Data Plans Starter Pack",
        description="5G voice/data contracts, term length variants, global roaming bundles, and fair use terms.",
        storefront_backend=storefront,
        merchant_backend=merchant,
        initial_products=products,
        initial_policies=policies,
        initial_listings=listings,
    )


def create_entertainment_starter_pack() -> CommerceStarterPack:
    """Create Starter Pack for Entertainment & Live Events (Concerts, Sports, Theater Tickets)."""
    products = [
        Product(
            product_id="ent_fest_soundwave_2026",
            title="Soundwave Music & Arts Festival 2026 - Weekend Pass",
            description="Three-day access to 4 outdoor stages, electronic and indie bands, food trucks, and light installations.",
            base_price=199.0,
            category="live_event",
            in_stock=True,
            tags=("entertainment", "festival", "concert", "music", "live"),
            variants=(
                ProductVariant(
                    variant_id="ent_tkt_ga_tier1",
                    title="General Admission (Early Bird)",
                    price=199.0,
                    sku="SW26-GA-T1",
                    in_stock=True,
                    inventory_quantity=80,
                    options=(
                        VariantOption(name="tier", value="GA"),
                        VariantOption(name="zone", value="general_lawn"),
                    ),
                ),
                ProductVariant(
                    variant_id="ent_tkt_vip_front",
                    title="VIP Front Stage Lounge Pass",
                    price=399.0,
                    sku="SW26-VIP-FRONT",
                    in_stock=True,
                    inventory_quantity=15,
                    options=(
                        VariantOption(name="tier", value="VIP"),
                        VariantOption(name="zone", value="vip_pit"),
                    ),
                ),
            ),
        ),
    ]

    policies = [
        Policy(
            policy_id="ent_pol_tickets",
            category=PolicyCategory.RETURNS,
            title="Live Event Ticketing & Non-Refundable Entry Rules",
            content_markdown="All ticket sales are final and non-refundable unless the entire festival is cancelled by the event organizer. Real-name verification is mandatory.",
        ),
    ]

    listings = [
        Listing(
            listing_id="list_ent_001",
            title=products[0].title,
            description=products[0].description,
            price=products[0].base_price,
            inventory_count=95,
            status=ListingStatus.ACTIVE,
            category=products[0].category,
            tags=products[0].tags,
        ),
        Listing(
            listing_id="list_ent_002",
            title="Backstage VIP Experience Pass",
            description="Access to VIP hospitality lounge and meet & greet.",
            price=499.0,
            inventory_count=10,
            status=ListingStatus.ACTIVE,
            category="live_event",
            tags=("vip", "backstage"),
        ),
    ]

    storefront = InMemoryStorefrontBackend(products=products, policies=policies)
    merchant = InMemoryMerchantBackend(listings=listings)

    return CommerceStarterPack(
        domain="entertainment",
        display_name="Live Entertainment & Event Ticketing Starter Pack",
        description="Music festivals, VIP lounge tiers, seating zones, and organizer real-name admission policies.",
        storefront_backend=storefront,
        merchant_backend=merchant,
        initial_products=products,
        initial_policies=policies,
        initial_listings=listings,
    )


VERTICAL_FACTORIES = {
    "retail": create_retail_starter_pack,
    "travel": create_travel_starter_pack,
    "telecom": create_telecom_starter_pack,
    "entertainment": create_entertainment_starter_pack,
}


def get_vertical_starter_pack(domain: VerticalDomain) -> CommerceStarterPack:
    """Retrieve an initialized vertical commerce starter pack by industry identifier."""
    factory = VERTICAL_FACTORIES.get(domain)
    if not factory:
        raise ValueError(f"Unknown commerce vertical domain '{domain}'. Valid options: {list(VERTICAL_FACTORIES.keys())}")
    return factory()

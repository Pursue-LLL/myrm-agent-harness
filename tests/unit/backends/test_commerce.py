"""Unit tests for Commerce backend protocols and in-memory reference implementations.

Tests StorefrontBackendProtocol and MerchantBackendProtocol contracts,
exceptions, and session-isolated operations.
"""

from __future__ import annotations

import pytest

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
from myrm_agent_harness.backends.commerce.protocols import (
    MerchantBackendProtocol,
    StorefrontBackendProtocol,
)
from myrm_agent_harness.backends.commerce.types import (
    ChangeType,
    CommerceRole,
    InventoryAlertSeverity,
    ListingStatus,
    MerchantSessionState,
    Money,
    OrderStatus,
    PolicyCategory,
    ProductFilter,
    ShoppingSessionState,
    VariantOption,
)


@pytest.mark.asyncio
async def test_storefront_backend_protocol_conformance() -> None:
    backend = InMemoryStorefrontBackend()
    assert isinstance(backend, StorefrontBackendProtocol)

    # 1. Search products
    results = await backend.search_products("runner")
    assert len(results) >= 1
    assert results[0].product_id == "prod_runner_01"

    # Search with category filter
    filtered = await backend.search_products(
        "",
        filters=ProductFilter(category="apparel"),
    )
    assert len(filtered) >= 1
    assert all(p.category == "apparel" for p in filtered)

    # 2. Product details
    details = await backend.get_product_details("prod_runner_01")
    assert details is not None
    assert details.title == "AeroStride Carbon Running Shoes"

    missing = await backend.get_product_details("non_existent_prod")
    assert missing is None

    # 3. Order history
    orders = await backend.get_orders("cust_001")
    assert len(orders) >= 1
    assert orders[0].order_id == "ord_9901"
    assert orders[0].status == OrderStatus.DELIVERED

    # 4. Policy search
    policies = await backend.search_policies("returns")
    assert len(policies) >= 1
    assert policies[0].category == PolicyCategory.RETURNS

    # 5. Cart operations
    session_id = "test_session_shopper_01"
    cart = await backend.get_cart(session_id)
    assert cart.session_id == session_id
    assert len(cart.lines) == 0

    # Add item
    add_res = await backend.add_to_cart(
        session_id=session_id,
        product_id="prod_runner_01",
        quantity=2,
    )
    assert add_res.action == "add"
    assert len(add_res.cart.lines) == 1
    assert add_res.cart.lines[0].quantity == 2
    line_id = add_res.cart.lines[0].line_id

    # Update item quantity
    update_res = await backend.update_cart_item(
        session_id=session_id,
        line_id=line_id,
        quantity=3,
    )
    assert update_res.action == "update"
    assert update_res.cart.lines[0].quantity == 3

    # Remove item
    remove_res = await backend.remove_from_cart(
        session_id=session_id,
        line_id=line_id,
    )
    assert remove_res.action == "remove"
    assert len(remove_res.cart.lines) == 0


@pytest.mark.asyncio
async def test_merchant_backend_protocol_conformance() -> None:
    backend = InMemoryMerchantBackend()
    assert isinstance(backend, MerchantBackendProtocol)

    # 1. Performance summary
    summary = await backend.get_performance_summary("last_7d")
    assert summary.gmv > 0
    assert summary.order_count > 0
    assert len(summary.top_products) > 0

    # 2. Catalog listing
    listing = await backend.get_listing("list_001")
    assert listing is not None
    assert listing.listing_id == "list_001"
    assert listing.status == ListingStatus.ACTIVE

    # 3. Two-phase staging flow
    staged = await backend.stage_listing_change(
        listing_id="list_001",
        change_type=ChangeType.PRICE_UPDATE,
        proposed_values=(("price", "165.0"),),
    )
    assert staged.listing_id == "list_001"
    assert staged.change_type == ChangeType.PRICE_UPDATE
    assert not staged.applied

    # Apply staged change
    applied = await backend.apply_staged_change(staged.change_id)
    assert applied.success
    assert applied.change_id == staged.change_id

    # Verify listing updated
    updated_listing = await backend.get_listing("list_001")
    assert updated_listing is not None
    assert updated_listing.price == 165.0

    # Staged change cannot be applied twice
    with pytest.raises(InvalidStagedChange):
        await backend.apply_staged_change(staged.change_id)

    # 4. Pricing context
    pricing = await backend.get_pricing_context("list_001")
    assert pricing.listing_id == "list_001"
    assert pricing.current_price == 165.0
    assert pricing.margin_pct > 0

    # 5. Inventory alerts
    alerts = await backend.get_inventory_alerts(min_severity="warning")
    assert len(alerts) >= 1
    assert alerts[0].severity in (InventoryAlertSeverity.WARNING, InventoryAlertSeverity.CRITICAL)


def test_session_state_and_domain_models() -> None:
    shopper_state = ShoppingSessionState(
        session_id="shopper_s1",
        customer_id="cust_alice",
        active_cart_id="cart_101",
    )
    assert shopper_state.customer_id == "cust_alice"
    assert shopper_state.active_cart_id == "cart_101"

    merchant_state = MerchantSessionState(
        session_id="merchant_s1",
        merchant_id="merchant_bob",
        authorized_permissions=("admin", "inventory_manager"),
    )
    assert merchant_state.merchant_id == "merchant_bob"
    assert "admin" in merchant_state.authorized_permissions

    money = Money(amount=19.99, currency="USD")
    assert money.amount == 19.99
    assert money.currency == "USD"

    opt = VariantOption(name="Size", value="XL")
    assert opt.name == "Size"
    assert opt.value == "XL"


def test_commerce_exceptions_hierarchy() -> None:
    err = CommerceError("Root commerce error")
    assert isinstance(err, Exception)

    not_offered = NotOffered("Feature not supported")
    assert isinstance(not_offered, CommerceError)

    unavailable = Unavailable("Out of stock")
    assert isinstance(unavailable, CommerceError)

    not_app = ChangeNotApplicable()
    assert isinstance(not_app, CommerceError)

    inv_staged = InvalidStagedChange()
    assert isinstance(inv_staged, CommerceError)


# ============================================================================
# Commerce Governance Gate Tests (OPTIONS_GATE & Cart Cap Governance)
# ============================================================================

def test_variant_options_resolution_no_variants() -> None:
    from myrm_agent_harness.backends.commerce import (
        Product,
        resolve_variant_options,
    )

    prod = Product(
        product_id="single_p1",
        title="Standard Sticker Pack",
        description="Pack of stickers",
        base_price=5.0,
        category="stationery",
        variants=(),
    )
    res = resolve_variant_options(prod)
    assert res.decision == "allowed"
    assert res.resolved_variant_id is None
    assert "no variants" in res.reason


def test_variant_options_resolution_held_when_options_unresolved() -> None:
    from myrm_agent_harness.backends.commerce import (
        Product,
        ProductVariant,
        VariantOption,
        resolve_variant_options,
    )

    variants = (
        ProductVariant(
            variant_id="var_red_m",
            title="Red / M",
            price=29.0,
            options=(VariantOption(name="Color", value="Red"), VariantOption(name="Size", value="M")),
        ),
        ProductVariant(
            variant_id="var_red_l",
            title="Red / L",
            price=29.0,
            options=(VariantOption(name="Color", value="Red"), VariantOption(name="Size", value="L")),
        ),
        ProductVariant(
            variant_id="var_blue_m",
            title="Blue / M",
            price=29.0,
            options=(VariantOption(name="Color", value="Blue"), VariantOption(name="Size", value="M")),
        ),
    )
    prod = Product(
        product_id="prod_tshirt",
        title="Classic T-Shirt",
        description="Cotton t-shirt with colors and sizes",
        base_price=29.0,
        category="apparel",
        variants=variants,
    )

    # 1. No options provided -> held with suggestion chips
    res_empty = resolve_variant_options(prod, selected_options=None)
    assert res_empty.decision == "held"
    assert "Color" in res_empty.missing_options
    assert "Size" in res_empty.missing_options
    assert set(res_empty.suggestion_chips["Color"]) == {"Red", "Blue"}
    assert set(res_empty.suggestion_chips["Size"]) == {"M", "L"}

    # 2. Partial option provided -> held with remaining missing option
    res_partial = resolve_variant_options(prod, selected_options={"Color": "Red"})
    assert res_partial.decision == "held"
    assert "Size" in res_partial.missing_options
    assert "Color" not in res_partial.missing_options

    # 3. Full matching options provided -> allowed and resolved
    res_full = resolve_variant_options(prod, selected_options={"Color": "Red", "Size": "L"})
    assert res_full.decision == "allowed"
    assert res_full.resolved_variant_id == "var_red_l"
    assert res_full.resolved_variant_title == "Red / L"

    # 4. Explicit valid variant ID supplied -> allowed
    res_explicit = resolve_variant_options(prod, explicit_variant_id="var_blue_m")
    assert res_explicit.decision == "allowed"
    assert res_explicit.resolved_variant_id == "var_blue_m"


def test_cart_cap_governance() -> None:
    from myrm_agent_harness.backends.commerce import (
        Cart,
        CartLine,
        CartCapLimits,
        check_cart_cap,
    )

    limits = CartCapLimits(max_quantity_per_item=5, max_cart_lines=3, max_total_quantity=10)

    # Base cart with 1 line of 3 items
    cart = Cart(
        cart_id="cart_test_1",
        session_id="sess_test",
        lines=(
            CartLine(
                line_id="line_1",
                product_id="prod_p1",
                variant_id="var_v1",
                quantity=3,
                unit_price=10.0,
                title="Item 1",
            ),
        ),
    )

    # 1. Adding 2 more of the same item -> total 5 <= 5 (allowed)
    chk1 = check_cart_cap(cart, variant_id="var_v1", adding_quantity=2, limits=limits)
    assert chk1.allowed is True
    assert chk1.decision == "allowed"

    # 2. Adding 3 more of the same item -> total 6 > 5 (blocked by per-item cap)
    chk2 = check_cart_cap(cart, variant_id="var_v1", adding_quantity=3, limits=limits)
    assert chk2.allowed is False
    assert chk2.decision == "blocked"
    assert "Per-item cap exceeded" in chk2.reason

    # 3. Reaching total cart lines limit
    full_lines_cart = Cart(
        cart_id="cart_test_2",
        session_id="sess_test",
        lines=(
            CartLine(line_id="l1", product_id="p1", variant_id="v1", quantity=1, unit_price=10.0, title="T1"),
            CartLine(line_id="l2", product_id="p2", variant_id="v2", quantity=1, unit_price=10.0, title="T2"),
            CartLine(line_id="l3", product_id="p3", variant_id="v3", quantity=1, unit_price=10.0, title="T3"),
        ),
    )
    # Adding a 4th distinct line -> blocked by max_cart_lines
    chk3 = check_cart_cap(full_lines_cart, variant_id="v4", adding_quantity=1, limits=limits)
    assert chk3.allowed is False
    assert "Cart lines cap reached" in chk3.reason

    # 4. Total units cap
    heavy_units_cart = Cart(
        cart_id="cart_test_3",
        session_id="sess_test",
        lines=(
            CartLine(line_id="l1", product_id="p1", variant_id="v1", quantity=5, unit_price=10.0, title="T1"),
            CartLine(line_id="l2", product_id="p2", variant_id="v2", quantity=4, unit_price=10.0, title="T2"),
        ),
    )
    # Total units is 9. Adding 2 more of a new line -> 11 > 10 (blocked by max_total_quantity)
    chk4 = check_cart_cap(heavy_units_cart, variant_id="v3", adding_quantity=2, limits=limits)
    assert chk4.allowed is False
    assert "Total cart unit cap exceeded" in chk4.reason


@pytest.mark.asyncio
async def test_cart_session_lock_serialization() -> None:
    from myrm_agent_harness.backends.commerce.gates import CartSessionLock

    lock_mgr = CartSessionLock()
    lock_sess1 = lock_mgr.get_lock("sess_100")
    lock_sess1_again = lock_mgr.get_lock("sess_100")
    lock_sess2 = lock_mgr.get_lock("sess_200")

    assert lock_sess1 is lock_sess1_again
    assert lock_sess1 is not lock_sess2

    # Verify locking behavior
    async with lock_sess1:
        assert lock_sess1.locked() is True


def test_cart_operation_receipt_fenced_id_only() -> None:
    from myrm_agent_harness.backends.commerce.gates import CartOperationReceipt

    receipt = CartOperationReceipt(
        status="success",
        cart_id="cart_abc",
        line_id="line_xyz",
        product_id="prod_runner_01",
        variant_id="var_red_42",
        quantity=2,
        unit_price=120.0,
        subtotal=240.0,
    )
    assert receipt.status == "success"
    assert receipt.product_id == "prod_runner_01"
    assert receipt.variant_id == "var_red_42"
    assert receipt.subtotal == 240.0
    # Confirm it does not include untrusted title field
    dumped = receipt.model_dump()
    assert "title" not in dumped
    assert "product_title" not in dumped



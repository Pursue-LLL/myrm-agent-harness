"""Tests for Product Variant Options Resolution and Cart Cap Governance Gate.

[INPUT]
- myrm_agent_harness.backends.commerce.gates::*
- myrm_agent_harness.backends.commerce.types::*

[OUTPUT]
- Unit tests verifying OPTIONS_GATE, suggestion chips, per-item and total cart line caps,
  pure ID-only receipt fencing, and session mutex serialization.

[POS]
Unit tests for commerce gate invariants and security fences.
"""

from __future__ import annotations

import asyncio
import pytest

from myrm_agent_harness.backends.commerce.gates import (
    CartCapLimits,
    CartOperationReceipt,
    CartSessionLock,
    check_cart_cap,
    extract_product_options_catalog,
    resolve_variant_options,
)
from myrm_agent_harness.backends.commerce.types import (
    Cart,
    CartLine,
    Product,
    ProductVariant,
    VariantOption,
)


@pytest.fixture
def multi_variant_product() -> Product:
    v1 = ProductVariant(
        variant_id="var_red_m",
        title="Ruby Red / Medium",
        price=59.0,
        options=(VariantOption("color", "red"), VariantOption("size", "m")),
        in_stock=True,
    )
    v2 = ProductVariant(
        variant_id="var_red_l",
        title="Ruby Red / Large",
        price=59.0,
        options=(VariantOption("color", "red"), VariantOption("size", "l")),
        in_stock=False,  # Out of stock
    )
    v3 = ProductVariant(
        variant_id="var_blue_m",
        title="Ocean Blue / Medium",
        price=59.0,
        options=(VariantOption("color", "blue"), VariantOption("size", "m")),
        in_stock=True,
    )
    return Product(
        product_id="prod_hoodie",
        title="Cozy Fleece Hoodie",
        description="Warm winter hoodie with multiple colors and sizes",
        base_price=59.0,
        category="apparel",
        in_stock=True,
        variants=(v1, v2, v3),
    )


@pytest.fixture
def simple_product() -> Product:
    return Product(
        product_id="prod_water_bottle",
        title="Stainless Steel Bottle",
        description="Standard 750ml thermal bottle",
        base_price=25.0,
        category="lifestyle",
        in_stock=True,
        variants=(),
    )


def test_options_catalog_extraction(multi_variant_product: Product) -> None:
    catalog = extract_product_options_catalog(multi_variant_product)
    assert set(catalog.keys()) == {"color", "size"}
    assert set(catalog["color"]) == {"red", "blue"}
    assert set(catalog["size"]) == {"m", "l"}


def test_resolve_options_simple_product(simple_product: Product) -> None:
    res = resolve_variant_options(simple_product)
    assert res.decision == "allowed"
    assert res.resolved_variant_id is None
    assert "no variants" in res.reason


def test_resolve_options_held_when_options_missing(multi_variant_product: Product) -> None:
    # 1. No options provided -> held with all suggestion chips
    res1 = resolve_variant_options(multi_variant_product, selected_options={})
    assert res1.decision == "held"
    assert "color" in res1.missing_options
    assert "size" in res1.missing_options
    assert "red" in res1.suggestion_chips["color"]

    # 2. Only partial option provided (color only) -> held
    res2 = resolve_variant_options(multi_variant_product, selected_options={"color": "red"})
    assert res2.decision == "held"
    assert res2.missing_options == ["size"]
    assert "m" in res2.suggestion_chips["size"]


def test_resolve_options_allowed_when_fully_settled(multi_variant_product: Product) -> None:
    res = resolve_variant_options(
        multi_variant_product,
        selected_options={"color": "blue", "size": "m"},
    )
    assert res.decision == "allowed"
    assert res.resolved_variant_id == "var_blue_m"
    assert res.resolved_variant_title == "Ocean Blue / Medium"


def test_resolve_options_blocked_when_out_of_stock(multi_variant_product: Product) -> None:
    res = resolve_variant_options(
        multi_variant_product,
        selected_options={"color": "red", "size": "l"},
    )
    assert res.decision == "blocked"
    assert res.resolved_variant_id == "var_red_l"
    assert "out of stock" in res.reason


def test_resolve_options_explicit_variant_id(multi_variant_product: Product) -> None:
    # Valid and in stock
    res1 = resolve_variant_options(multi_variant_product, explicit_variant_id="var_red_m")
    assert res1.decision == "allowed"
    assert res1.resolved_variant_id == "var_red_m"

    # Out of stock
    res2 = resolve_variant_options(multi_variant_product, explicit_variant_id="var_red_l")
    assert res2.decision == "blocked"

    # Nonexistent
    res3 = resolve_variant_options(multi_variant_product, explicit_variant_id="var_invalid")
    assert res3.decision == "blocked"


def test_check_cart_cap_per_item_and_lines() -> None:
    limits = CartCapLimits(max_quantity_per_item=5, max_cart_lines=3, max_total_quantity=10)

    cart = Cart(
        cart_id="c_1",
        session_id="s_1",
        lines=(
            CartLine(line_id="l_1", product_id="p_1", variant_id="v_1", quantity=3, unit_price=10.0, title="T1"),
            CartLine(line_id="l_2", product_id="p_2", variant_id="v_2", quantity=2, unit_price=15.0, title="T2"),
        ),
    )

    # 1. Allowed add
    res_ok = check_cart_cap(cart, variant_id="v_1", adding_quantity=2, limits=limits)
    assert res_ok.decision == "allowed"
    assert res_ok.allowed is True

    # 2. Exceeds per-item cap (3 + 3 = 6 > 5)
    res_per_item = check_cart_cap(cart, variant_id="v_1", adding_quantity=3, limits=limits)
    assert res_per_item.decision == "blocked"
    assert "Per-item cap exceeded" in str(res_per_item.reason)

    # 3. Exceeds line cap: adding 2 new distinct lines
    cart_full_lines = Cart(
        cart_id="c_2",
        session_id="s_2",
        lines=(
            CartLine(line_id="l_1", product_id="p_1", variant_id="v_1", quantity=1, unit_price=10.0, title="T1"),
            CartLine(line_id="l_2", product_id="p_2", variant_id="v_2", quantity=1, unit_price=15.0, title="T2"),
            CartLine(line_id="l_3", product_id="p_3", variant_id="v_3", quantity=1, unit_price=20.0, title="T3"),
        ),
    )
    res_line_cap = check_cart_cap(cart_full_lines, variant_id="v_new", adding_quantity=1, limits=limits)
    assert res_line_cap.decision == "blocked"
    assert "Cart lines cap reached" in str(res_line_cap.reason)

    # 4. Exceeds total quantity cap (total was 3, adding 8 -> 11 > 10)
    res_total_cap = check_cart_cap(cart_full_lines, variant_id="v_1", adding_quantity=8, limits=limits)
    assert res_total_cap.decision == "blocked"


def test_cart_operation_receipt_id_only_sanitization() -> None:
    receipt = CartOperationReceipt(
        status="success",
        cart_id="c_123",
        line_id="l_456",
        product_id="prod_hoodie",
        variant_id="var_red_m",
        quantity=2,
        unit_price=59.0,
        subtotal=118.0,
    )
    # Ensure title field does not exist in receipt to prevent prompt injection
    assert not hasattr(receipt, "title")
    assert receipt.product_id == "prod_hoodie"
    assert receipt.variant_id == "var_red_m"


@pytest.mark.asyncio
async def test_cart_session_lock_serialization() -> None:
    lock_registry = CartSessionLock()
    lock_a1 = lock_registry.get_lock("session_a")
    lock_a2 = lock_registry.get_lock("session_a")
    lock_b = lock_registry.get_lock("session_b")

    # Same session returns the exact same lock
    assert lock_a1 is lock_a2
    # Different session returns an independent lock
    assert lock_a1 is not lock_b

    # Verify lock behavior
    async with lock_a1:
        assert lock_a2.locked()

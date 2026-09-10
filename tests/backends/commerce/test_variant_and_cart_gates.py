"""Unit tests for Harness Commerce Gates: Options Resolution, Cart Caps, and Receipts."""

from __future__ import annotations

import asyncio
import pytest

from myrm_agent_harness.backends.commerce.gates import (
    CartCapLimits,
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
    return Product(
        product_id="prod_sneaker",
        title="Ultra Runner Sneaker",
        description="High performance running shoe",
        base_price=120.0,
        category="footwear",
        in_stock=True,
        variants=(
            ProductVariant(
                variant_id="var_white_8",
                title="White / Size 8",
                price=120.0,
                in_stock=True,
                options=(
                    VariantOption(name="Color", value="White"),
                    VariantOption(name="Size", value="8"),
                ),
            ),
            ProductVariant(
                variant_id="var_white_9",
                title="White / Size 9",
                price=120.0,
                in_stock=True,
                options=(
                    VariantOption(name="Color", value="White"),
                    VariantOption(name="Size", value="9"),
                ),
            ),
            ProductVariant(
                variant_id="var_black_8",
                title="Black / Size 8",
                price=125.0,
                in_stock=False,  # Out of stock
                options=(
                    VariantOption(name="Color", value="Black"),
                    VariantOption(name="Size", value="8"),
                ),
            ),
        ),
    )


@pytest.fixture
def single_item_product() -> Product:
    return Product(
        product_id="prod_socks",
        title="Running Socks",
        description="Breathable cotton socks",
        base_price=15.0,
        category="accessories",
        in_stock=True,
        variants=(),
    )


def test_extract_product_options_catalog(multi_variant_product: Product) -> None:
    catalog = extract_product_options_catalog(multi_variant_product)
    assert "Color" in catalog
    assert "Size" in catalog
    assert sorted(catalog["Color"]) == ["Black", "White"]
    assert sorted(catalog["Size"]) == ["8", "9"]


def test_resolve_options_for_single_item(single_item_product: Product) -> None:
    res = resolve_variant_options(single_item_product)
    assert res.decision == "allowed"
    assert res.resolved_variant_id is None
    assert "standard single item" in res.reason


def test_resolve_options_missing_options_returns_held(multi_variant_product: Product) -> None:
    # 1. No options supplied at all
    res = resolve_variant_options(multi_variant_product, selected_options={})
    assert res.decision == "held"
    assert "Color" in res.missing_options
    assert "Size" in res.missing_options
    assert "Color" in res.suggestion_chips
    assert "Size" in res.suggestion_chips

    # 2. Only Color supplied, Size missing
    res_partial = resolve_variant_options(multi_variant_product, selected_options={"Color": "White"})
    assert res_partial.decision == "held"
    assert res_partial.missing_options == ["Size"]
    assert "Size" in res_partial.suggestion_chips
    assert sorted(res_partial.suggestion_chips["Size"]) == ["8", "9"]


def test_resolve_options_full_match_allowed(multi_variant_product: Product) -> None:
    res = resolve_variant_options(
        multi_variant_product,
        selected_options={"color": "white", "size": "9"},
    )
    assert res.decision == "allowed"
    assert res.resolved_variant_id == "var_white_9"
    assert res.resolved_variant_title == "White / Size 9"


def test_resolve_options_out_of_stock_blocked(multi_variant_product: Product) -> None:
    res = resolve_variant_options(
        multi_variant_product,
        selected_options={"Color": "Black", "Size": "8"},
    )
    assert res.decision == "blocked"
    assert res.resolved_variant_id == "var_black_8"
    assert "out of stock" in res.reason.lower()


def test_resolve_options_explicit_variant_id(multi_variant_product: Product) -> None:
    # Valid and in stock
    res = resolve_variant_options(multi_variant_product, explicit_variant_id="var_white_8")
    assert res.decision == "allowed"
    assert res.resolved_variant_id == "var_white_8"

    # Out of stock
    res_oos = resolve_variant_options(multi_variant_product, explicit_variant_id="var_black_8")
    assert res_oos.decision == "blocked"
    assert "out of stock" in res_oos.reason.lower()

    # Non-existent
    res_non_exist = resolve_variant_options(multi_variant_product, explicit_variant_id="var_invalid")
    assert res_non_exist.decision == "blocked"
    assert "does not exist" in res_non_exist.reason.lower()


def test_cart_cap_per_item_overflow() -> None:
    limits = CartCapLimits(max_quantity_per_item=5, max_cart_lines=10, max_total_quantity=20)
    cart = Cart(
        cart_id="cart_1",
        session_id="s1",
        lines=(
            CartLine(
                line_id="line_1",
                product_id="prod_sneaker",
                variant_id="var_white_8",
                quantity=4,
                unit_price=120.0,
                title="Sneaker",
            ),
        ),
    )

    # Adding 1 should succeed (4 + 1 = 5 <= 5)
    check_ok = check_cart_cap(cart, variant_id="var_white_8", adding_quantity=1, limits=limits)
    assert check_ok.allowed is True
    assert check_ok.decision == "allowed"

    # Adding 2 should be blocked (4 + 2 = 6 > 5)
    check_fail = check_cart_cap(cart, variant_id="var_white_8", adding_quantity=2, limits=limits)
    assert check_fail.allowed is False
    assert check_fail.decision == "blocked"
    assert "Per-item cap exceeded" in str(check_fail.reason)


def test_cart_cap_lines_and_total_quantity() -> None:
    limits = CartCapLimits(max_quantity_per_item=10, max_cart_lines=2, max_total_quantity=10)
    cart = Cart(
        cart_id="cart_2",
        session_id="s2",
        lines=(
            CartLine(line_id="l1", product_id="p1", variant_id="v1", quantity=4, unit_price=10.0, title="P1"),
            CartLine(line_id="l2", product_id="p2", variant_id="v2", quantity=4, unit_price=20.0, title="P2"),
        ),
    )

    # 1. Cart line count limit reached (already 2 lines)
    check_line = check_cart_cap(cart, variant_id="v3", adding_quantity=1, limits=limits)
    assert check_line.allowed is False
    assert "Cart lines cap reached" in str(check_line.reason)

    # 2. Existing line addition within lines limit, but exceeds total quantity (8 + 3 = 11 > 10)
    check_total = check_cart_cap(cart, variant_id="v1", adding_quantity=3, limits=limits)
    assert check_total.allowed is False
    assert "Total cart unit cap exceeded" in str(check_total.reason)


@pytest.mark.asyncio
async def test_cart_session_lock_serialization() -> None:
    session_lock_registry = CartSessionLock()
    lock = session_lock_registry.get_lock("session_xyz")

    order_of_execution: list[int] = []

    async def worker(task_id: int, delay: float) -> None:
        async with lock:
            order_of_execution.append(task_id)
            await asyncio.sleep(delay)

    # Launch two concurrent tasks; worker 1 will hold lock first
    task1 = asyncio.create_task(worker(1, 0.05))
    await asyncio.sleep(0.01)
    task2 = asyncio.create_task(worker(2, 0.01))

    await asyncio.gather(task1, task2)
    assert order_of_execution == [1, 2]

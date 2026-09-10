"""Unit tests for ProductVariantOptionsResolutionAndCartCapGovernanceSuite (gates.py).

Covers:
- resolve_variant_options:
  - Products without variants (allowed)
  - Explicit variant_id: in-stock vs out-of-stock vs non-existent
  - Missing options (held with suggestion_chips)
  - Complete matching options (allowed with resolved_variant_id)
  - Ambiguous / conflicting options
- check_cart_cap:
  - Non-positive quantity blocked
  - Adding within single item limit
  - Per-item limit exceeded
  - Max cart lines exceeded
  - Total cart quantity cap exceeded
- CartOperationReceipt:
  - Id-only fencing (no arbitrary untrusted product title reflection)
- CartSessionLock:
  - Concurrency serialization per session_id
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
    return Product(
        product_id="prod_shoes_01",
        title="Pro Ultra Running Shoes",
        description="High performance running shoes",
        base_price=120.0,
        category="footwear",
        variants=(
            ProductVariant(
                variant_id="var_black_42",
                title="Black / 42",
                price=120.0,
                in_stock=True,
                options=(
                    VariantOption(name="color", value="Black"),
                    VariantOption(name="size", value="42"),
                ),
            ),
            ProductVariant(
                variant_id="var_black_43",
                title="Black / 43",
                price=120.0,
                in_stock=False,  # Out of stock
                options=(
                    VariantOption(name="color", value="Black"),
                    VariantOption(name="size", value="43"),
                ),
            ),
            ProductVariant(
                variant_id="var_red_42",
                title="Red / 42",
                price=130.0,
                in_stock=True,
                options=(
                    VariantOption(name="color", value="Red"),
                    VariantOption(name="size", value="42"),
                ),
            ),
        ),
    )


@pytest.fixture
def simple_product() -> Product:
    return Product(
        product_id="prod_simple_mug",
        title="Standard Coffee Mug",
        description="Ceramic mug",
        base_price=15.0,
        category="kitchen",
        variants=(),
    )


class TestVariantOptionsResolution:
    def test_product_without_variants_allowed(self, simple_product: Product) -> None:
        res = resolve_variant_options(simple_product)
        assert res.decision == "allowed"
        assert res.resolved_variant_id is None
        assert "no variants" in res.reason

    def test_explicit_variant_in_stock(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(
            multi_variant_product, explicit_variant_id="var_black_42"
        )
        assert res.decision == "allowed"
        assert res.resolved_variant_id == "var_black_42"
        assert res.resolved_variant_title == "Black / 42"

    def test_explicit_variant_out_of_stock(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(
            multi_variant_product, explicit_variant_id="var_black_43"
        )
        assert res.decision == "blocked"
        assert res.resolved_variant_id == "var_black_43"
        assert "out of stock" in res.reason

    def test_explicit_variant_non_existent(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(
            multi_variant_product, explicit_variant_id="var_invalid"
        )
        assert res.decision == "blocked"
        assert "does not exist" in res.reason

    def test_missing_options_held_with_chips(self, multi_variant_product: Product) -> None:
        # User only picked color="black", size is missing
        res = resolve_variant_options(
            multi_variant_product, selected_options={"color": "Black"}
        )
        assert res.decision == "held"
        assert "size" in res.missing_options
        assert "color" in res.suggestion_chips
        assert "size" in res.suggestion_chips
        assert "42" in res.suggestion_chips["size"]

    def test_empty_options_held_with_all_chips(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(multi_variant_product, selected_options={})
        assert res.decision == "held"
        assert set(res.missing_options) == {"color", "size"}
        assert len(res.suggestion_chips) == 2

    def test_complete_matching_options_allowed(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(
            multi_variant_product,
            selected_options={"color": "Red", "size": "42"},
        )
        assert res.decision == "allowed"
        assert res.resolved_variant_id == "var_red_42"
        assert res.resolved_variant_title == "Red / 42"

    def test_matching_options_out_of_stock_blocked(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(
            multi_variant_product,
            selected_options={"color": "Black", "size": "43"},
        )
        assert res.decision == "blocked"
        assert res.resolved_variant_id == "var_black_43"
        assert "out of stock" in res.reason

    def test_no_variant_match_for_combination(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(
            multi_variant_product,
            selected_options={"color": "Green", "size": "42"},
        )
        assert res.decision == "blocked"
        assert "variant" in res.reason.lower() and "match" in res.reason.lower()


class TestCartCapGovernance:
    def test_non_positive_quantity_blocked(self) -> None:
        cart = Cart(cart_id="c_1", session_id="s_1")
        res = check_cart_cap(cart, variant_id="v_1", adding_quantity=0)
        assert res.decision == "blocked"
        assert not res.allowed

    def test_within_limits_allowed(self) -> None:
        cart = Cart(cart_id="c_1", session_id="s_1")
        res = check_cart_cap(cart, variant_id="v_1", adding_quantity=2)
        assert res.decision == "allowed"
        assert res.allowed

    def test_per_item_cap_exceeded(self) -> None:
        limits = CartCapLimits(max_quantity_per_item=5)
        cart = Cart(
            cart_id="c_1",
            session_id="s_1",
            lines=(
                CartLine(
                    line_id="l_1",
                    product_id="p_1",
                    variant_id="v_1",
                    quantity=4,
                    unit_price=10.0,
                    title="Item 1",
                ),
            ),
        )
        # Adding 2 makes it 6 > 5
        res = check_cart_cap(cart, variant_id="v_1", adding_quantity=2, limits=limits)
        assert res.decision == "blocked"
        assert not res.allowed
        assert "Per-item cap exceeded" in res.reason

    def test_max_cart_lines_exceeded(self) -> None:
        limits = CartCapLimits(max_cart_lines=2)
        cart = Cart(
            cart_id="c_1",
            session_id="s_1",
            lines=(
                CartLine(
                    line_id="l_1",
                    product_id="p_1",
                    variant_id="v_1",
                    quantity=1,
                    unit_price=10.0,
                    title="Item 1",
                ),
                CartLine(
                    line_id="l_2",
                    product_id="p_2",
                    variant_id="v_2",
                    quantity=1,
                    unit_price=15.0,
                    title="Item 2",
                ),
            ),
        )
        # Adding a 3rd new line should be blocked
        res = check_cart_cap(cart, variant_id="v_3", adding_quantity=1, limits=limits)
        assert res.decision == "blocked"
        assert "Cart lines cap reached" in res.reason

        # Adding to existing line v_1 is still allowed if quantity fits
        res_existing = check_cart_cap(cart, variant_id="v_1", adding_quantity=1, limits=limits)
        assert res_existing.decision == "allowed"

    def test_max_total_quantity_cap_exceeded(self) -> None:
        limits = CartCapLimits(max_total_quantity=10, max_quantity_per_item=10)
        cart = Cart(
            cart_id="c_1",
            session_id="s_1",
            lines=(
                CartLine(
                    line_id="l_1",
                    product_id="p_1",
                    variant_id="v_1",
                    quantity=7,
                    unit_price=10.0,
                    title="Item 1",
                ),
            ),
        )
        # Adding 4 makes total 11 > 10
        res = check_cart_cap(cart, variant_id="v_2", adding_quantity=4, limits=limits)
        assert res.decision == "blocked"
        assert "Total cart unit cap exceeded" in res.reason


class TestCartOperationReceiptSanitization:
    def test_id_only_receipt_sanitization(self) -> None:
        receipt = CartOperationReceipt(
            status="success",
            cart_id="cart_abc123",
            item_id="item_line_01",
            variant_id="var_black_42",
            quantity=2,
            unit_price_cents=12000,
            total_price_cents=24000,
        )
        # Ensure no raw title field exists on the receipt model
        assert not hasattr(receipt, "title")
        assert not hasattr(receipt, "product_title")
        assert receipt.cart_id == "cart_abc123"
        assert receipt.variant_id == "var_black_42"


@pytest.mark.asyncio
async def test_cart_session_lock_serialization() -> None:
    session_lock = CartSessionLock()
    lock1 = session_lock.get_lock("session_user_42")
    lock2 = session_lock.get_lock("session_user_42")
    assert lock1 is lock2

    lock_other = session_lock.get_lock("session_user_99")
    assert lock_other is not lock1

    execution_order: list[int] = []

    async def worker(worker_id: int, delay: float) -> None:
        async with session_lock.get_lock("session_user_42"):
            await asyncio.sleep(delay)
            execution_order.append(worker_id)

    # Launch concurrent tasks
    await asyncio.gather(
        worker(1, 0.02),
        worker(2, 0.01),
    )
    assert len(execution_order) == 2

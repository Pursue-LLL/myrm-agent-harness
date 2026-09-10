"""Unit tests for product variant options resolution and cart capacity governance gate.

[INPUT]
- myrm_agent_harness.backends.commerce.types::Product, ProductVariant, Cart, CartLine, VariantOption
- myrm_agent_harness.backends.commerce.gates::resolve_variant_options, check_cart_cap, CartCapLimits, CartSessionLock, CartOperationReceipt

[OUTPUT]
- Test suite verifying OPTIONS_GATE, suggestion chips, line & quantity caps, pure ID receipts, and session mutex.
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
        product_id="prod_sneakers",
        title="Speed Runner Sneakers",
        description="High-performance running shoes",
        base_price=120.0,
        category="footwear",
        variants=(
            ProductVariant(
                variant_id="var_red_42",
                title="Red / 42",
                price=120.0,
                in_stock=True,
                options=(
                    VariantOption(name="Color", value="Red"),
                    VariantOption(name="Size", value="42"),
                ),
            ),
            ProductVariant(
                variant_id="var_red_43",
                title="Red / 43",
                price=120.0,
                in_stock=False,
                options=(
                    VariantOption(name="Color", value="Red"),
                    VariantOption(name="Size", value="43"),
                ),
            ),
            ProductVariant(
                variant_id="var_blue_42",
                title="Blue / 42",
                price=125.0,
                in_stock=True,
                options=(
                    VariantOption(name="Color", value="Blue"),
                    VariantOption(name="Size", value="42"),
                ),
            ),
        ),
    )


@pytest.fixture
def single_item_product() -> Product:
    return Product(
        product_id="prod_book",
        title="AI Architecture Handbook",
        description="Comprehensive guide to AI architectures",
        base_price=49.9,
        category="books",
        variants=(),
    )


class TestVariantOptionsGate:
    """Tests for multi-specification option convergence and suggestion chips."""

    def test_single_item_without_variants_allowed(self, single_item_product: Product) -> None:
        res = resolve_variant_options(single_item_product)
        assert res.decision == "allowed"
        assert res.resolved_variant_id is None

    def test_explicit_valid_variant_id_allowed(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(
            multi_variant_product,
            explicit_variant_id="var_red_42",
        )
        assert res.decision == "allowed"
        assert res.resolved_variant_id == "var_red_42"
        assert res.resolved_variant_title == "Red / 42"

    def test_explicit_out_of_stock_variant_blocked(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(
            multi_variant_product,
            explicit_variant_id="var_red_43",
        )
        assert res.decision == "blocked"
        assert "out of stock" in res.reason.lower()

    def test_explicit_nonexistent_variant_blocked(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(
            multi_variant_product,
            explicit_variant_id="var_invalid_999",
        )
        assert res.decision == "blocked"
        assert "does not exist" in res.reason.lower()

    def test_missing_options_returns_held_with_chips(self, multi_variant_product: Product) -> None:
        # User only selected Color=Red, missing Size
        res = resolve_variant_options(
            multi_variant_product,
            selected_options={"Color": "Red"},
        )
        assert res.decision == "held"
        assert "Size" in res.missing_options
        assert "Size" in res.suggestion_chips
        assert set(res.suggestion_chips["Size"]) == {"42", "43"}

    def test_empty_options_returns_held_with_all_chips(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(multi_variant_product, selected_options={})
        assert res.decision == "held"
        assert set(res.missing_options) == {"Color", "Size"}
        assert "Color" in res.suggestion_chips
        assert "Size" in res.suggestion_chips

    def test_complete_matching_options_allowed(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(
            multi_variant_product,
            selected_options={"color": "blue", "size": "42"},
        )
        assert res.decision == "allowed"
        assert res.resolved_variant_id == "var_blue_42"
        assert res.resolved_variant_title == "Blue / 42"

    def test_complete_matching_out_of_stock_blocked(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(
            multi_variant_product,
            selected_options={"color": "red", "size": "43"},
        )
        assert res.decision == "blocked"
        assert res.resolved_variant_id == "var_red_43"
        assert "out of stock" in res.reason.lower()

    def test_nonexistent_options_combination_blocked(self, multi_variant_product: Product) -> None:
        res = resolve_variant_options(
            multi_variant_product,
            selected_options={"color": "green", "size": "50"},
        )
        assert res.decision == "blocked"
        assert "no matching variant" in res.reason.lower()


class TestCartCapGovernance:
    """Tests for line count and quantity limits in cart operations."""

    def test_invalid_quantity_blocked(self) -> None:
        cart = Cart(cart_id="c_1", session_id="s_1")
        res = check_cart_cap(cart, variant_id="v_1", adding_quantity=0)
        assert res.decision == "blocked"
        assert res.allowed is False

    def test_per_item_cap_enforced(self) -> None:
        cart = Cart(
            cart_id="c_1",
            session_id="s_1",
            lines=(
                CartLine(
                    line_id="l_1",
                    product_id="p_1",
                    variant_id="v_1",
                    quantity=8,
                    unit_price=10.0,
                    title="Item 1",
                ),
            ),
        )
        limits = CartCapLimits(max_quantity_per_item=10)
        # Adding 2 makes it 10 -> allowed
        res1 = check_cart_cap(cart, variant_id="v_1", adding_quantity=2, limits=limits)
        assert res1.decision == "allowed"
        assert res1.allowed is True

        # Adding 3 makes it 11 -> blocked
        res2 = check_cart_cap(cart, variant_id="v_1", adding_quantity=3, limits=limits)
        assert res2.decision == "blocked"
        assert res2.allowed is False
        assert "per-item cap exceeded" in res2.reason.lower()

    def test_cart_lines_cap_enforced(self) -> None:
        # Create a cart with 2 lines, limit is 2 lines
        lines = tuple(
            CartLine(
                line_id=f"l_{i}",
                product_id=f"p_{i}",
                variant_id=f"v_{i}",
                quantity=1,
                unit_price=10.0,
                title=f"Item {i}",
            )
            for i in range(2)
        )
        cart = Cart(cart_id="c_1", session_id="s_1", lines=lines)
        limits = CartCapLimits(max_cart_lines=2)

        # Adding to existing line is allowed
        res_existing = check_cart_cap(cart, variant_id="v_0", adding_quantity=1, limits=limits)
        assert res_existing.decision == "allowed"

        # Adding a new line is blocked
        res_new = check_cart_cap(cart, variant_id="v_new", adding_quantity=1, limits=limits)
        assert res_new.decision == "blocked"
        assert "cart lines cap reached" in res_new.reason.lower()

    def test_total_cart_units_cap_enforced(self) -> None:
        cart = Cart(
            cart_id="c_1",
            session_id="s_1",
            lines=(
                CartLine(
                    line_id="l_1",
                    product_id="p_1",
                    variant_id="v_1",
                    quantity=15,
                    unit_price=10.0,
                    title="Item 1",
                ),
            ),
        )
        limits = CartCapLimits(max_total_quantity=20)
        # Adding 5 -> allowed (total 20)
        res1 = check_cart_cap(cart, variant_id="v_2", adding_quantity=5, limits=limits)
        assert res1.decision == "allowed"

        # Adding 6 -> blocked (total 21)
        res2 = check_cart_cap(cart, variant_id="v_2", adding_quantity=6, limits=limits)
        assert res2.decision == "blocked"
        assert "total cart unit cap exceeded" in res2.reason.lower()


class TestCartReceiptAndSessionLock:
    """Tests for pure ID receipt fencing and session concurrency locking."""

    def test_cart_operation_receipt_pure_id_fencing(self) -> None:
        receipt = CartOperationReceipt(
            status="success",
            cart_id="cart_999",
            line_id="line_888",
            product_id="prod_777",
            variant_id="var_666",
            quantity=2,
            unit_price=49.5,
            subtotal=99.0,
        )
        data = receipt.model_dump()
        # Verify receipt has NO 'title' or 'name' fields that can be injected
        assert "title" not in data
        assert "description" not in data
        assert data["cart_id"] == "cart_999"
        assert data["product_id"] == "prod_777"
        assert data["variant_id"] == "var_666"

    @pytest.mark.asyncio
    async def test_session_lock_serializes_concurrent_writes(self) -> None:
        lock_registry = CartSessionLock()
        session_id = "session_xyz"
        execution_order: list[int] = []

        async def worker(worker_id: int, delay: float) -> None:
            async with lock_registry.get_lock(session_id):
                execution_order.append(worker_id)
                await asyncio.sleep(delay)

        # Worker 1 takes lock first, Worker 2 must wait
        await asyncio.gather(
            worker(1, 0.05),
            worker(2, 0.01),
        )
        assert execution_order == [1, 2]

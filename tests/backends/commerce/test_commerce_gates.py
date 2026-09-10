"""Unit tests for Product Variant Options Resolution and Cart Cap Governance Gates.

[INPUT]
- myrm_agent_harness.backends.commerce.gates::resolve_variant_options, check_cart_cap,
  CartCapLimits, CartOperationReceipt, CartSessionLock, extract_product_options_catalog
- myrm_agent_harness.backends.commerce.types::Product, ProductVariant, VariantOption, Cart, CartLine

[OUTPUT]
- Test suites for:
  1. Product Variant Options convergence, held status, and chip suggestion.
  2. Cart capacity, per-item, line count, and total quantity cap governance.
  3. Session-level lock serialization and sanitized ID-only receipts.

[POS]
Harness-level commerce gate unit tests verifying OPTIONS_GATE and CAP_GOVERNANCE.
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
        product_id="prod_runner_01",
        title="AeroStride Carbon Running Shoes",
        description="High-cushion marathon shoes with responsive carbon-fiber plate.",
        base_price=180.0,
        category="footwear",
        in_stock=True,
        tags=("running", "marathon"),
        variants=(
            ProductVariant(
                variant_id="var_red_42",
                title="Red / EU 42",
                price=180.0,
                in_stock=True,
                inventory_quantity=10,
                options=(
                    VariantOption(name="color", value="red"),
                    VariantOption(name="size", value="42"),
                ),
            ),
            ProductVariant(
                variant_id="var_red_43",
                title="Red / EU 43",
                price=180.0,
                in_stock=True,
                inventory_quantity=5,
                options=(
                    VariantOption(name="color", value="red"),
                    VariantOption(name="size", value="43"),
                ),
            ),
            ProductVariant(
                variant_id="var_blue_42",
                title="Blue / EU 42",
                price=185.0,
                in_stock=False,  # Out of stock
                inventory_quantity=0,
                options=(
                    VariantOption(name="color", value="blue"),
                    VariantOption(name="size", value="42"),
                ),
            ),
        ),
    )


@pytest.fixture
def simple_product() -> Product:
    return Product(
        product_id="prod_tee_01",
        title="Merino Trail Breathable T-Shirt",
        description="Ultra-fine 100% merino wool shirt.",
        base_price=65.0,
        category="apparel",
        in_stock=True,
        variants=(),
    )


class TestVariantOptionsResolutionGate:
    """Test OPTIONS_GATE: disambiguation, held status, suggestion chips, stock verification."""

    def test_simple_product_without_variants_allowed_immediately(
        self, simple_product: Product
    ) -> None:
        res = resolve_variant_options(simple_product)
        assert res.decision == "allowed"
        assert res.resolved_variant_id is None
        assert not res.missing_options

    def test_multi_variant_product_without_options_is_held_with_chips(
        self, multi_variant_product: Product
    ) -> None:
        res = resolve_variant_options(multi_variant_product)
        assert res.decision == "held"
        assert set(res.missing_options) == {"color", "size"}
        assert "red" in res.suggestion_chips["color"]
        assert "blue" in res.suggestion_chips["color"]
        assert "42" in res.suggestion_chips["size"]
        assert "43" in res.suggestion_chips["size"]

    def test_partial_options_specified_is_held_with_remaining_chips(
        self, multi_variant_product: Product
    ) -> None:
        res = resolve_variant_options(
            multi_variant_product,
            selected_options={"color": "red"},
        )
        assert res.decision == "held"
        assert res.missing_options == ["size"]
        assert "42" in res.suggestion_chips["size"]

    def test_fully_specified_in_stock_variant_is_allowed(
        self, multi_variant_product: Product
    ) -> None:
        res = resolve_variant_options(
            multi_variant_product,
            selected_options={"color": "red", "size": "42"},
        )
        assert res.decision == "allowed"
        assert res.resolved_variant_id == "var_red_42"
        assert res.resolved_variant_title == "Red / EU 42"

    def test_fully_specified_out_of_stock_variant_is_blocked(
        self, multi_variant_product: Product
    ) -> None:
        res = resolve_variant_options(
            multi_variant_product,
            selected_options={"color": "blue", "size": "42"},
        )
        assert res.decision == "blocked"
        assert res.resolved_variant_id == "var_blue_42"
        assert "out of stock" in res.reason.lower()

    def test_explicit_variant_id_handling(
        self, multi_variant_product: Product
    ) -> None:
        # Valid in stock
        valid_res = resolve_variant_options(
            multi_variant_product,
            explicit_variant_id="var_red_43",
        )
        assert valid_res.decision == "allowed"
        assert valid_res.resolved_variant_id == "var_red_43"

        # Valid out of stock
        oos_res = resolve_variant_options(
            multi_variant_product,
            explicit_variant_id="var_blue_42",
        )
        assert oos_res.decision == "blocked"

        # Non-existent variant id
        missing_res = resolve_variant_options(
            multi_variant_product,
            explicit_variant_id="var_unknown_99",
        )
        assert missing_res.decision == "blocked"

    def test_extract_product_options_catalog(
        self, multi_variant_product: Product
    ) -> None:
        catalog = extract_product_options_catalog(multi_variant_product)
        assert set(catalog.keys()) == {"color", "size"}
        assert set(catalog["color"]) == {"red", "blue"}
        assert set(catalog["size"]) == {"42", "43"}


class TestCartCapGovernanceGate:
    """Test CAP_GOVERNANCE: per-item limits, cart line caps, total unit caps."""

    def test_positive_quantity_enforcement(self) -> None:
        empty_cart = Cart(cart_id="c1", session_id="s1", lines=())
        res = check_cart_cap(empty_cart, variant_id="v1", adding_quantity=0)
        assert res.decision == "blocked"
        assert not res.allowed

        negative_res = check_cart_cap(empty_cart, variant_id="v1", adding_quantity=-2)
        assert negative_res.decision == "blocked"

    def test_per_item_quantity_cap(self) -> None:
        cart = Cart(
            cart_id="c1",
            session_id="s1",
            lines=(
                CartLine(
                    line_id="l1",
                    product_id="p1",
                    variant_id="v1",
                    quantity=8,
                    unit_price=10.0,
                    title="Item 1",
                ),
            ),
        )
        limits = CartCapLimits(max_quantity_per_item=10)

        # Adding 2 makes it 10 (allowed)
        res_ok = check_cart_cap(cart, variant_id="v1", adding_quantity=2, limits=limits)
        assert res_ok.decision == "allowed"
        assert res_ok.allowed

        # Adding 3 makes it 11 (blocked)
        res_blocked = check_cart_cap(cart, variant_id="v1", adding_quantity=3, limits=limits)
        assert res_blocked.decision == "blocked"
        assert not res_blocked.allowed
        assert "Per-item cap exceeded" in str(res_blocked.reason)

    def test_cart_lines_count_cap(self) -> None:
        # Cart with 3 lines
        cart = Cart(
            cart_id="c1",
            session_id="s1",
            lines=(
                CartLine(line_id="l1", product_id="p1", variant_id="v1", quantity=1, unit_price=10.0, title="I1"),
                CartLine(line_id="l2", product_id="p2", variant_id="v2", quantity=1, unit_price=10.0, title="I2"),
                CartLine(line_id="l3", product_id="p3", variant_id="v3", quantity=1, unit_price=10.0, title="I3"),
            ),
        )
        limits = CartCapLimits(max_cart_lines=3)

        # Adding to existing line is allowed even if lines count is at cap
        res_existing = check_cart_cap(cart, variant_id="v2", adding_quantity=1, limits=limits)
        assert res_existing.decision == "allowed"

        # Adding a new line when at cap is blocked
        res_new = check_cart_cap(cart, variant_id="v4_new", adding_quantity=1, limits=limits)
        assert res_new.decision == "blocked"
        assert "Cart lines cap reached" in str(res_new.reason)

    def test_total_cart_units_cap(self) -> None:
        cart = Cart(
            cart_id="c1",
            session_id="s1",
            lines=(
                CartLine(line_id="l1", product_id="p1", variant_id="v1", quantity=15, unit_price=10.0, title="I1"),
                CartLine(line_id="l2", product_id="p2", variant_id="v2", quantity=10, unit_price=10.0, title="I2"),
            ),
        )
        limits = CartCapLimits(max_total_quantity=30, max_quantity_per_item=50)

        # Current total is 25. Adding 5 -> 30 (allowed)
        res_ok = check_cart_cap(cart, variant_id="v3_new", adding_quantity=5, limits=limits)
        assert res_ok.decision == "allowed"

        # Adding 6 -> 31 (blocked)
        res_blocked = check_cart_cap(cart, variant_id="v3_new", adding_quantity=6, limits=limits)
        assert res_blocked.decision == "blocked"
        assert "Total cart unit cap exceeded" in str(res_blocked.reason)


class TestIdOnlyReceiptAndSessionLock:
    """Test sanitized Id-only receipts and session mutex serialization."""

    def test_sanitized_id_only_receipt_structure(self) -> None:
        receipt = CartOperationReceipt(
            status="success",
            cart_id="cart_session_99",
            line_id="line_abc123",
            product_id="prod_runner_01",
            variant_id="var_red_42",
            quantity=2,
            unit_price=180.0,
            subtotal=360.0,
        )
        dumped = receipt.model_dump()
        # Verify title is strictly excluded from receipt to prevent title injection
        assert "title" not in dumped
        assert dumped["status"] == "success"
        assert dumped["variant_id"] == "var_red_42"
        assert dumped["subtotal"] == 360.0

    @pytest.mark.asyncio
    async def test_session_lock_serialization(self) -> None:
        lock_registry = CartSessionLock()
        lock1 = lock_registry.get_lock("sess_alpha")
        lock2 = lock_registry.get_lock("sess_alpha")
        assert lock1 is lock2

        lock_beta = lock_registry.get_lock("sess_beta")
        assert lock1 is not lock_beta

        execution_order: list[int] = []

        async def worker(worker_id: int, delay: float) -> None:
            async with lock_registry.get_lock("sess_alpha"):
                execution_order.append(worker_id)
                await asyncio.sleep(delay)

        await asyncio.gather(
            worker(1, 0.02),
            worker(2, 0.01),
        )
        assert len(execution_order) == 2

"""Unit tests for Product Variant Options Resolution and Cart Cap Governance Gate.

[INPUT]
- myrm_agent_harness.backends.commerce::*

[OUTPUT]
- TestProductVariantOptionsResolution: 多规格选项收敛与推荐芯片测试
- TestCartCapGovernance: 购物车限额、行数熔断与总量风控测试
- TestIdOnlyReceipt: 纯 ID 安全回执与防标题注入测试
- TestCartSessionLock: 会话加车写入序列化并发锁测试

[POS]
Tests verifying Anthropic Claude Commerce Agents `gates.py` parity in Myrm Harness.
"""

from __future__ import annotations

import asyncio
import pytest

from myrm_agent_harness.backends.commerce import (
    Cart,
    CartCapLimits,
    CartLine,
    CartOperationReceipt,
    CartSessionLock,
    Product,
    ProductVariant,
    VariantOption,
    check_cart_cap,
    extract_product_options_catalog,
    resolve_variant_options,
)


@pytest.fixture
def product_with_variants() -> Product:
    return Product(
        product_id="prod_jacket",
        title="Alpine Technical Shell",
        description="Waterproof mountaineering jacket",
        base_price=350.0,
        category="outdoor",
        in_stock=True,
        variants=(
            ProductVariant(
                variant_id="var_jacket_black_m",
                title="Black / M",
                price=350.0,
                in_stock=True,
                options=(
                    VariantOption(name="Color", value="Black"),
                    VariantOption(name="Size", value="M"),
                ),
            ),
            ProductVariant(
                variant_id="var_jacket_black_l",
                title="Black / L",
                price=350.0,
                in_stock=True,
                options=(
                    VariantOption(name="Color", value="Black"),
                    VariantOption(name="Size", value="L"),
                ),
            ),
            ProductVariant(
                variant_id="var_jacket_red_m",
                title="Red / M",
                price=360.0,
                in_stock=False,  # Out of stock
                options=(
                    VariantOption(name="Color", value="Red"),
                    VariantOption(name="Size", value="M"),
                ),
            ),
        ),
    )


@pytest.fixture
def product_without_variants() -> Product:
    return Product(
        product_id="prod_water_bottle",
        title="Titanium Water Bottle 750ml",
        description="Ultralight flask",
        base_price=45.0,
        category="accessories",
        in_stock=True,
        variants=(),
    )


class TestProductVariantOptionsResolution:
    """Test suite for variant option disambiguation and suggestion chips."""

    def test_product_without_variants_allowed_immediately(
        self, product_without_variants: Product
    ) -> None:
        res = resolve_variant_options(product_without_variants)
        assert res.decision == "allowed"
        assert res.resolved_variant_id is None
        assert not res.suggestion_chips

    def test_extract_options_catalog(self, product_with_variants: Product) -> None:
        catalog = extract_product_options_catalog(product_with_variants)
        assert set(catalog.keys()) == {"Color", "Size"}
        assert set(catalog["Color"]) == {"Black", "Red"}
        assert set(catalog["Size"]) == {"M", "L"}

    def test_unspecified_options_returns_held_with_chips(
        self, product_with_variants: Product
    ) -> None:
        # User/agent called add_to_cart without specifying color or size
        res = resolve_variant_options(product_with_variants, selected_options=None)
        assert res.decision == "held"
        assert set(res.missing_options) == {"Color", "Size"}
        assert "Color" in res.suggestion_chips
        assert "Size" in res.suggestion_chips
        assert "Black" in res.suggestion_chips["Color"]

    def test_partial_options_returns_held_with_remaining_chips(
        self, product_with_variants: Product
    ) -> None:
        # User only specified Color="Black", Size is missing
        res = resolve_variant_options(
            product_with_variants, selected_options={"Color": "Black"}
        )
        assert res.decision == "held"
        assert res.missing_options == ["Size"]
        assert "Size" in res.suggestion_chips

    def test_fully_converged_options_allowed(
        self, product_with_variants: Product
    ) -> None:
        res = resolve_variant_options(
            product_with_variants,
            selected_options={"Color": "Black", "Size": "L"},
        )
        assert res.decision == "allowed"
        assert res.resolved_variant_id == "var_jacket_black_l"
        assert res.resolved_variant_title == "Black / L"

    def test_out_of_stock_variant_blocked(
        self, product_with_variants: Product
    ) -> None:
        res = resolve_variant_options(
            product_with_variants,
            selected_options={"Color": "Red", "Size": "M"},
        )
        assert res.decision == "blocked"
        assert res.resolved_variant_id == "var_jacket_red_m"
        assert "out of stock" in res.reason.lower()

    def test_explicit_variant_id_bypass_with_verification(
        self, product_with_variants: Product
    ) -> None:
        res = resolve_variant_options(
            product_with_variants, explicit_variant_id="var_jacket_black_m"
        )
        assert res.decision == "allowed"
        assert res.resolved_variant_id == "var_jacket_black_m"

        # Invalid explicit variant id
        res_invalid = resolve_variant_options(
            product_with_variants, explicit_variant_id="var_non_existent"
        )
        assert res_invalid.decision == "blocked"


class TestCartCapGovernance:
    """Test suite for line count, item quantity, and total cart quota governance."""

    def test_zero_or_negative_quantity_blocked(self) -> None:
        cart = Cart(cart_id="c1", session_id="s1")
        res = check_cart_cap(cart, variant_id="v1", adding_quantity=0)
        assert res.decision == "blocked"
        assert not res.allowed

    def test_per_item_cap_breached(self) -> None:
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

        # Adding 3 makes it 11 -> blocked
        res = check_cart_cap(cart, variant_id="v1", adding_quantity=3, limits=limits)
        assert res.decision == "blocked"
        assert not res.allowed
        assert "per-item cap exceeded" in res.reason.lower()

        # Adding 2 makes it 10 -> allowed
        res_ok = check_cart_cap(cart, variant_id="v1", adding_quantity=2, limits=limits)
        assert res_ok.decision == "allowed"
        assert res_ok.allowed

    def test_max_cart_lines_limit(self) -> None:
        existing_lines = tuple(
            CartLine(
                line_id=f"l_{i}",
                product_id=f"p_{i}",
                variant_id=f"v_{i}",
                quantity=1,
                unit_price=10.0,
                title=f"Item {i}",
            )
            for i in range(5)
        )
        cart = Cart(cart_id="c1", session_id="s1", lines=existing_lines)
        limits = CartCapLimits(max_cart_lines=5)

        # Adding existing variant line is allowed (doesn't create new line)
        res_existing = check_cart_cap(cart, variant_id="v_1", adding_quantity=1, limits=limits)
        assert res_existing.decision == "allowed"

        # Adding a brand new line is blocked by lines limit
        res_new = check_cart_cap(cart, variant_id="v_brand_new", adding_quantity=1, limits=limits)
        assert res_new.decision == "blocked"
        assert "cart lines cap reached" in res_new.reason.lower()

    def test_max_total_cart_units_cap(self) -> None:
        cart = Cart(
            cart_id="c1",
            session_id="s1",
            lines=(
                CartLine(
                    line_id="l1",
                    product_id="p1",
                    variant_id="v1",
                    quantity=15,
                    unit_price=10.0,
                    title="Item 1",
                ),
            ),
        )
        limits = CartCapLimits(max_total_quantity=20, max_quantity_per_item=20)

        # 15 + 6 = 21 > 20 -> blocked
        res = check_cart_cap(cart, variant_id="v2", adding_quantity=6, limits=limits)
        assert res.decision == "blocked"
        assert "total cart unit cap exceeded" in res.reason.lower()


class TestIdOnlyReceipt:
    """Test suite for sanitized id-only confirmation outputs to prevent prompt injection."""

    def test_receipt_structure_sanitization(self) -> None:
        receipt = CartOperationReceipt(
            status="success",
            cart_id="cart_abc123",
            product_id="prod_jacket",
            variant_id="var_jacket_black_m",
            quantity=2,
            unit_price=350.0,
            subtotal=700.0,
        )
        dump = receipt.model_dump()
        # Ensure only deterministic IDs and financial figures are present
        assert dump["cart_id"] == "cart_abc123"
        assert dump["product_id"] == "prod_jacket"
        assert dump["variant_id"] == "var_jacket_black_m"
        assert dump["quantity"] == 2
        assert "title" not in dump  # Title is isolated to prevent injection


class TestCartSessionLock:
    """Test suite for session-level cart mutation serialization."""

    @pytest.mark.asyncio
    async def test_session_serialization_mutex(self) -> None:
        lock_registry = CartSessionLock()
        lock = lock_registry.get_lock("session_user_42")

        execution_order: list[str] = []

        async def worker(tag: str, delay: float) -> None:
            async with lock:
                execution_order.append(f"{tag}_start")
                await asyncio.sleep(delay)
                execution_order.append(f"{tag}_end")

        await asyncio.gather(worker("A", 0.02), worker("B", 0.01))

        # A must fully finish before B starts, or vice versa
        assert execution_order in [
            ["A_start", "A_end", "B_start", "B_end"],
            ["B_start", "B_end", "A_start", "A_end"],
        ]


class TestGatedAddToCart:
    """Test suite for the end-to-end gated_add_to_cart pipeline."""

    @pytest.mark.asyncio
    async def test_gated_add_to_cart_held_when_options_missing(
        self, product_with_variants: Product
    ) -> None:
        from myrm_agent_harness.backends.commerce import (
            InMemoryStorefrontBackend,
            gated_add_to_cart,
        )

        backend = InMemoryStorefrontBackend(products=[product_with_variants])
        session_id = "sess_customer_1"

        # Missing options -> held with chips
        receipt = await gated_add_to_cart(
            backend=backend,
            session_id=session_id,
            product_id="prod_jacket",
            quantity=1,
        )
        assert receipt.status == "held"
        assert "Color" in receipt.suggestion_chips
        assert "Size" in receipt.suggestion_chips

    @pytest.mark.asyncio
    async def test_gated_add_to_cart_success_with_id_only_receipt(
        self, product_with_variants: Product
    ) -> None:
        from myrm_agent_harness.backends.commerce import (
            InMemoryStorefrontBackend,
            gated_add_to_cart,
        )

        backend = InMemoryStorefrontBackend(products=[product_with_variants])
        session_id = "sess_customer_2"

        # Explicit variant specified -> success
        receipt = await gated_add_to_cart(
            backend=backend,
            session_id=session_id,
            product_id="prod_jacket",
            quantity=2,
            variant_id="var_jacket_black_m",
        )
        assert receipt.status == "success"
        assert receipt.product_id == "prod_jacket"
        assert receipt.variant_id == "var_jacket_black_m"
        assert receipt.quantity == 2
        assert receipt.subtotal == 700.0
        assert not hasattr(receipt, "title") or getattr(receipt, "title", None) is None

    @pytest.mark.asyncio
    async def test_gated_add_to_cart_cap_blocked(
        self, product_with_variants: Product
    ) -> None:
        from myrm_agent_harness.backends.commerce import (
            InMemoryStorefrontBackend,
            gated_add_to_cart,
        )

        backend = InMemoryStorefrontBackend(products=[product_with_variants])
        session_id = "sess_customer_3"
        limits = CartCapLimits(max_quantity_per_item=5)

        # Quantity exceeds cap -> blocked
        receipt = await gated_add_to_cart(
            backend=backend,
            session_id=session_id,
            product_id="prod_jacket",
            quantity=6,
            variant_id="var_jacket_black_m",
            limits=limits,
        )
        assert receipt.status == "blocked"
        assert "per-item cap exceeded" in str(receipt.gate_reason).lower()


"""Product Variant Options Resolution and Cart Cap Governance Gate.

[INPUT]
- typing::Literal
- pydantic::BaseModel, Field
- myrm_agent_harness.backends.commerce.types::Product, ProductVariant, Cart, CartLine, VariantOption
- myrm_agent_harness.backends.commerce.exceptions::CommerceError, Unavailable

[OUTPUT]
- GateDecision: 门禁决策枚举 ("allowed" | "held" | "blocked")
- VariantOptionsResolution: 多规格选项收敛判定结果与推荐芯片
- CartCapLimits: 购物车配额配置
- CartCapCheckResult: 购物车容量与配额检查结果
- CartOperationReceipt: 纯 ID 安全加车回执（防标题注入）
- CartSessionLock: 会话级加车写操作序列化锁
- resolve_variant_options(): 变体选项收敛解析器
- check_cart_cap(): 购物车容量与配额校验器

[POS]
Harness-level commerce gate ensuring options convergence before cart write,
enforcing line and quantity caps, and providing sanitized id-only receipts.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Literal

from pydantic import BaseModel, Field

from myrm_agent_harness.backends.commerce.types import Cart, Product, ProductVariant, VariantOption

GateDecision = Literal["allowed", "held", "blocked"]


class VariantOptionsResolution(BaseModel):
    """Result of evaluating whether product variant options have fully converged."""

    decision: GateDecision
    product_id: str
    resolved_variant_id: str | None = None
    resolved_variant_title: str | None = None
    missing_options: list[str] = Field(default_factory=list)
    suggestion_chips: dict[str, list[str]] = Field(default_factory=dict)
    reason: str


class CartCapLimits(BaseModel):
    """Configuration limits for cart line counts and quantities."""

    max_quantity_per_item: int = Field(default=10, ge=1, description="Max quantity per single variant line")
    max_cart_lines: int = Field(default=25, ge=1, description="Max distinct items/lines in cart")
    max_total_quantity: int = Field(default=50, ge=1, description="Max total units across all items in cart")


class CartCapCheckResult(BaseModel):
    """Outcome of evaluating cart capacity caps."""

    decision: GateDecision
    allowed: bool
    reason: str | None = None
    current_quantity: int = 0
    adding_quantity: int = 0
    limit: int = 0


class CartOperationReceipt(BaseModel):
    """Fenced, id-only receipt for completed cart mutations.

    Does not echo untrusted catalog titles back into model prompts to prevent title injection.
    """

    status: Literal["success", "held", "blocked"]
    cart_id: str
    line_id: str | None = None
    product_id: str | None = None
    variant_id: str | None = None
    quantity: int = 0
    unit_price: float = 0.0
    subtotal: float = 0.0
    gate_reason: str | None = None
    suggestion_chips: dict[str, list[str]] = Field(default_factory=dict)


def extract_product_options_catalog(product: Product) -> dict[str, list[str]]:
    """Extract all distinct option dimensions and their available values from product variants."""
    options_map: dict[str, list[str]] = {}
    for variant in product.variants:
        for opt in variant.options:
            if opt.name not in options_map:
                options_map[opt.name] = []
            if opt.value not in options_map[opt.name]:
                options_map[opt.name].append(opt.value)
    return options_map


def resolve_variant_options(
    product: Product,
    selected_options: tuple[VariantOption, ...] | dict[str, str] | None = None,
    explicit_variant_id: str | None = None,
) -> VariantOptionsResolution:
    """Evaluate whether product variant options are fully settled.

    If the product has variants and the options do not converge to a single variant,
    the operation is HELD with suggestion chips for each missing or unresolved option.
    """
    if not product.variants:
        return VariantOptionsResolution(
            decision="allowed",
            product_id=product.product_id,
            resolved_variant_id=None,
            resolved_variant_title=None,
            reason="Product has no variants; standard single item selected.",
        )

    # 1. If an explicit variant_id is supplied and valid
    if explicit_variant_id:
        for v in product.variants:
            if v.variant_id == explicit_variant_id:
                if not v.in_stock:
                    return VariantOptionsResolution(
                        decision="blocked",
                        product_id=product.product_id,
                        resolved_variant_id=v.variant_id,
                        reason=f"Variant '{v.variant_id}' is currently out of stock.",
                    )
                return VariantOptionsResolution(
                    decision="allowed",
                    product_id=product.product_id,
                    resolved_variant_id=v.variant_id,
                    resolved_variant_title=v.title,
                    reason="Explicit variant specified and verified in stock.",
                )
        return VariantOptionsResolution(
            decision="blocked",
            product_id=product.product_id,
            reason=f"Variant '{explicit_variant_id}' does not exist on product '{product.product_id}'.",
        )

    # Normalize user-selected options
    normalized_selected: dict[str, str] = {}
    if isinstance(selected_options, dict):
        normalized_selected = {k.strip().lower(): v.strip().lower() for k, v in selected_options.items()}
    elif isinstance(selected_options, tuple):
        normalized_selected = {opt.name.strip().lower(): opt.value.strip().lower() for opt in selected_options}

    # 2. Extract options catalog
    options_catalog = extract_product_options_catalog(product)
    missing: list[str] = []
    chips: dict[str, list[str]] = {}

    for opt_name, opt_values in options_catalog.items():
        opt_key = opt_name.strip().lower()
        if opt_key not in normalized_selected or not normalized_selected[opt_key]:
            missing.append(opt_name)
            chips[opt_name] = list(opt_values)

    if missing:
        return VariantOptionsResolution(
            decision="held",
            product_id=product.product_id,
            missing_options=missing,
            suggestion_chips=options_catalog,
            reason=f"Options not fully specified. Please select: {', '.join(missing)}.",
        )

    # 3. Match against variants
    matched_variants: list[ProductVariant] = []
    for variant in product.variants:
        var_opts = {opt.name.strip().lower(): opt.value.strip().lower() for opt in variant.options}
        matches = all(var_opts.get(k) == v for k, v in normalized_selected.items())
        if matches:
            matched_variants.append(variant)

    if len(matched_variants) == 1:
        target = matched_variants[0]
        if not target.in_stock:
            return VariantOptionsResolution(
                decision="blocked",
                product_id=product.product_id,
                resolved_variant_id=target.variant_id,
                reason=f"Selected specification '{target.title}' is currently out of stock.",
            )
        return VariantOptionsResolution(
            decision="allowed",
            product_id=product.product_id,
            resolved_variant_id=target.variant_id,
            resolved_variant_title=target.title,
            reason="Specification fully converged to single in-stock variant.",
        )

    if len(matched_variants) == 0:
        return VariantOptionsResolution(
            decision="blocked",
            product_id=product.product_id,
            suggestion_chips=options_catalog,
            reason="No matching variant found; no variant matches the given options combination.",
        )

    # Multiple matches (still ambiguous)
    return VariantOptionsResolution(
        decision="held",
        product_id=product.product_id,
        suggestion_chips=options_catalog,
        reason="Multiple variants match current options; further disambiguation required.",
    )


def check_cart_cap(
    current_cart: Cart | None = None,
    variant_id: str | None = None,
    adding_quantity: int | None = None,
    limits: CartCapLimits | None = None,
    *,
    cart: Cart | None = None,
    product_id: str | None = None,
    quantity: int | None = None,
) -> CartCapCheckResult:
    """Verify that adding items does not exceed line, item, or total cart limits."""
    target_cart = current_cart if current_cart is not None else cart
    if target_cart is None:
        raise ValueError("Either current_cart or cart must be provided.")
    target_vid = variant_id if variant_id is not None else product_id
    target_qty = adding_quantity if adding_quantity is not None else (quantity if quantity is not None else 1)

    active_limits = limits or CartCapLimits()

    if target_qty <= 0:
        return CartCapCheckResult(
            decision="blocked",
            allowed=False,
            reason="Adding quantity must be strictly greater than 0.",
            current_quantity=0,
            adding_quantity=target_qty,
            limit=1,
        )

    # 1. Check existing quantity for this line
    existing_line_quantity = 0
    is_new_line = True
    total_existing_units = target_cart.total_quantity if hasattr(target_cart, "total_quantity") else sum(getattr(l, "quantity", 0) for l in getattr(target_cart, "lines", ()))
    cart_lines = getattr(target_cart, "lines", ())

    for line in cart_lines:
        line_var_id = getattr(line, "variant_id", None)
        line_prod_id = getattr(line, "product_id", None)
        if target_vid and (line_var_id == target_vid or line_prod_id == target_vid):
            existing_line_quantity = getattr(line, "quantity", 0)
            is_new_line = False

    new_line_quantity = existing_line_quantity + target_qty

    # 2. Check per-item cap
    max_per_item = active_limits.max_quantity_per_line if hasattr(active_limits, "max_quantity_per_line") and active_limits.max_quantity_per_line else active_limits.max_quantity_per_item
    if new_line_quantity > max_per_item:
        return CartCapCheckResult(
            decision="blocked",
            allowed=False,
            reason=(
                f"Per-item cap exceeded: cannot hold {new_line_quantity} units "
                f"(limit: {max_per_item})."
            ),
            current_quantity=existing_line_quantity,
            adding_quantity=target_qty,
            limit=max_per_item,
        )

    # 3. Check distinct cart line count limit
    if is_new_line and len(cart_lines) >= active_limits.max_cart_lines:
        return CartCapCheckResult(
            decision="blocked",
            allowed=False,
            reason=f"Cart lines cap reached: maximum {active_limits.max_cart_lines} distinct items allowed.",
            current_quantity=len(cart_lines),
            adding_quantity=1,
            limit=active_limits.max_cart_lines,
        )

    # 4. Check total units cap
    new_total_units = total_existing_units + target_qty
    if new_total_units > active_limits.max_total_quantity:
        return CartCapCheckResult(
            decision="blocked",
            allowed=False,
            reason=(
                f"Total cart unit cap exceeded: adding {adding_quantity} units would reach {new_total_units} "
                f"(limit: {active_limits.max_total_quantity})."
            ),
            current_quantity=total_existing_units,
            adding_quantity=target_qty,
            limit=active_limits.max_total_quantity,
        )

    return CartCapCheckResult(
        decision="allowed",
        allowed=True,
        current_quantity=existing_line_quantity,
        adding_quantity=target_qty,
        limit=active_limits.max_quantity_per_item,
    )


class CartSessionLock:
    """Thread-safe and async-safe mutex registry per session.

    Ensures cart modifications within the same session are serialized,
    preventing concurrent overwrites or quota bypasses.
    """

    def __init__(self) -> None:
        self._async_locks: dict[str, asyncio.Lock] = {}
        self._registry_lock = threading.Lock()

    def get_lock(self, session_id: str) -> asyncio.Lock:
        with self._registry_lock:
            if session_id not in self._async_locks:
                self._async_locks[session_id] = asyncio.Lock()
            return self._async_locks[session_id]


async def gated_add_to_cart(
    backend: Any,  # StorefrontBackendProtocol duck-typed to prevent circular imports
    session_id: str,
    product_id: str,
    quantity: int = 1,
    *,
    variant_id: str | None = None,
    selected_options: tuple[VariantOption, ...] | dict[str, str] | None = None,
    limits: CartCapLimits | None = None,
    session_lock: CartSessionLock | None = None,
) -> CartOperationReceipt:
    """Execute a guarded add-to-cart operation through OPTIONS_GATE and CAP_GOVERNANCE.

    1. Enforces single-turn options convergence: holds and returns suggestion chips if unresolved.
    2. Enforces session-level serialized write locking to prevent race conditions.
    3. Enforces per-item, line-count, and total cart unit caps.
    4. Returns a sanitized, fenced, id-only receipt (CartOperationReceipt) to prevent title injection.
    """
    product = await backend.get_product_details(product_id)
    if not product:
        return CartOperationReceipt(
            status="blocked",
            cart_id=f"cart_{session_id}",
            product_id=product_id,
            gate_reason=f"Product '{product_id}' does not exist.",
        )

    # 1. Evaluate OPTIONS_GATE
    options_res = resolve_variant_options(
        product,
        selected_options=selected_options,
        explicit_variant_id=variant_id,
    )

    if options_res.decision == "held":
        return CartOperationReceipt(
            status="held",
            cart_id=f"cart_{session_id}",
            product_id=product_id,
            gate_reason=options_res.reason,
            suggestion_chips=options_res.suggestion_chips,
        )

    if options_res.decision == "blocked":
        return CartOperationReceipt(
            status="blocked",
            cart_id=f"cart_{session_id}",
            product_id=product_id,
            variant_id=options_res.resolved_variant_id,
            gate_reason=options_res.reason,
            suggestion_chips=options_res.suggestion_chips,
        )

    effective_variant_id = options_res.resolved_variant_id

    # 2. Session serialization lock
    lock = session_lock.get_lock(session_id) if session_lock else None

    async def _perform_guarded_write() -> CartOperationReceipt:
        current_cart = await backend.get_cart(session_id)

        # 3. Evaluate Cart Cap Governance
        cap_result = check_cart_cap(
            current_cart=current_cart,
            variant_id=effective_variant_id,
            adding_quantity=quantity,
            limits=limits,
        )

        if not cap_result.allowed:
            return CartOperationReceipt(
                status="blocked",
                cart_id=current_cart.cart_id,
                product_id=product_id,
                variant_id=effective_variant_id,
                quantity=quantity,
                gate_reason=cap_result.reason,
            )

        # 4. Perform actual write
        update_result = await backend.add_to_cart(
            session_id=session_id,
            product_id=product_id,
            quantity=quantity,
            variant_id=effective_variant_id,
        )

        # Locate updated line
        modified_line = next(
            (line for line in update_result.cart.lines if line.line_id == update_result.modified_line_id),
            None,
        )

        return CartOperationReceipt(
            status="success",
            cart_id=update_result.cart.cart_id,
            line_id=update_result.modified_line_id,
            product_id=product_id,
            variant_id=effective_variant_id,
            quantity=modified_line.quantity if modified_line else quantity,
            unit_price=modified_line.unit_price if modified_line else 0.0,
            subtotal=update_result.cart.subtotal,
            gate_reason=None,
        )

    if lock:
        async with lock:
            return await _perform_guarded_write()
    else:
        return await _perform_guarded_write()


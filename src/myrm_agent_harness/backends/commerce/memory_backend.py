"""In-memory reference implementations of Storefront and Merchant backends.

[INPUT]
- .types::Product, ProductVariant, ProductFilter, Cart, CartLine, CartUpdateResult,
  Order, Policy, PolicySearchResult, PerformanceSummary, TopProductMetric, Listing,
  StagedChange, ApplyResult, PricingContext, InventoryAlert, VariantOption, ChangeType,
  ListingStatus, InventoryAlertSeverity, OrderStatus, PolicyCategory
- .exceptions::Unavailable, NotOffered, InvalidStagedChange, ChangeNotApplicable
- .protocols::StorefrontBackendProtocol, MerchantBackendProtocol

[OUTPUT]
- InMemoryStorefrontBackend: 内存级 C端导购与交易后端
- InMemoryMerchantBackend: 内存级 B端商家运营后端

[POS]
Lightweight, zero-dependency reference backends for testing, evaluation,
local prototypes, and sandbox environments.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from myrm_agent_harness.backends.commerce.exceptions import (
    ChangeNotApplicable,
    InvalidStagedChange,
    Unavailable,
)
from myrm_agent_harness.backends.commerce.protocols import (
    MerchantBackendProtocol,
    StorefrontBackendProtocol,
)
from myrm_agent_harness.backends.commerce.types import (
    ApplyResult,
    Cart,
    CartLine,
    CartUpdateResult,
    ChangeType,
    InventoryAlert,
    InventoryAlertSeverity,
    Listing,
    ListingStatus,
    Order,
    OrderLine,
    OrderStatus,
    PerformanceSummary,
    Policy,
    PolicyCategory,
    PolicySearchResult,
    PricingContext,
    Product,
    ProductFilter,
    StagedChange,
    TopProductMetric,
    VariantOption,
)


class InMemoryStorefrontBackend(StorefrontBackendProtocol):
    """In-memory Storefront backend implementation."""

    def __init__(
        self,
        products: list[Product] | None = None,
        orders: list[Order] | None = None,
        policies: list[Policy] | None = None,
    ) -> None:
        self._products: dict[str, Product] = {
            p.product_id: p for p in (products or self._default_products())
        }
        self._orders: dict[str, list[Order]] = {}
        for order in (orders or self._default_orders()):
            self._orders.setdefault(order.customer_id, []).append(order)
        self._policies: list[Policy] = list(policies or self._default_policies())
        self._carts: dict[str, Cart] = {}

    async def search_products(
        self,
        query: str,
        *,
        filters: ProductFilter | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[Product]:
        q = query.strip().lower()
        results: list[Product] = []

        for p in self._products.values():
            text_corpus = f"{p.product_id} {p.title} {p.description} {p.category} {' '.join(p.tags)}".lower()
            if q and q not in text_corpus:
                stem = q.rstrip("s").rstrip("er").rstrip("ing")
                if not (len(stem) >= 3 and stem in text_corpus):
                    continue
            if filters:
                if filters.category and p.category.lower() != filters.category.lower():
                    continue
                if filters.in_stock_only and not p.in_stock:
                    continue
                if filters.min_price is not None and p.base_price < filters.min_price:
                    continue
                if filters.max_price is not None and p.base_price > filters.max_price:
                    continue
                if filters.tags and not any(tag in p.tags for tag in filters.tags):
                    continue
            results.append(p)

        return results[offset : offset + limit]

    async def get_product_details(self, product_id: str) -> Product | None:
        return self._products.get(product_id)

    async def get_product(self, product_id: str) -> Product | None:
        """Alias for get_product_details."""
        return await self.get_product_details(product_id)

    async def get_policies(self) -> list[Policy]:
        """Return all active store policies."""
        return list(self._policies)

    async def get_orders(self, customer_id: str, *, limit: int = 10) -> list[Order]:
        orders = self._orders.get(customer_id, [])
        return orders[:limit]

    async def search_policies(self, query: str) -> list[PolicySearchResult]:
        q = query.strip().lower()
        results: list[PolicySearchResult] = []
        for policy in self._policies:
            content_lower = policy.content_markdown.lower()
            title_lower = policy.title.lower()
            if q in title_lower or q in content_lower:
                idx = content_lower.find(q)
                start = max(0, idx - 40)
                end = min(len(policy.content_markdown), idx + 80)
                excerpt = policy.content_markdown[start:end].strip()
                score = 0.9 if q in title_lower else 0.7
                results.append(
                    PolicySearchResult(
                        policy_id=policy.policy_id,
                        title=policy.title,
                        category=policy.category,
                        excerpt=excerpt,
                        score=score,
                    )
                )
        return results

    async def get_cart(self, session_id: str) -> Cart:
        if session_id not in self._carts:
            self._carts[session_id] = Cart(
                cart_id=f"cart_{session_id}",
                session_id=session_id,
                lines=(),
            )
        return self._carts[session_id]

    async def add_to_cart(
        self,
        session_id: str,
        product_id: str,
        *,
        quantity: int = 1,
        variant_id: str | None = None,
        selected_options: tuple[VariantOption, ...] = (),
    ) -> CartUpdateResult:
        if quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {quantity}")

        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")

        product = self._products.get(product_id)
        if not product or not product.in_stock:
            raise Unavailable(
                f"Product {product_id} is unavailable or does not exist.",
                item_id=product_id,
            )

        unit_price = product.base_price
        title = product.title
        chosen_variant_id = variant_id

        if product.variants:
            if not variant_id:
                available_ids = [v.variant_id for v in product.variants if v.in_stock]
                raise Unavailable(
                    f"Product {product_id} requires selecting a variant.",
                    item_id=product_id,
                    available_variant_ids=available_ids,
                )
            variant_match = next((v for v in product.variants if v.variant_id == variant_id), None)
            if not variant_match or not variant_match.in_stock:
                available_ids = [v.variant_id for v in product.variants if v.in_stock]
                raise Unavailable(
                    f"Variant {variant_id} is out of stock.",
                    item_id=variant_id,
                    available_variant_ids=available_ids,
                )
            unit_price = variant_match.price
            title = f"{product.title} - {variant_match.title}"

        cart = await self.get_cart(session_id)
        existing_lines = list(cart.lines)
        line_match = next(
            (
                l
                for l in existing_lines
                if l.product_id == product_id and l.variant_id == chosen_variant_id
            ),
            None,
        )

        if line_match:
            updated_lines = [
                CartLine(
                    line_id=l.line_id,
                    product_id=l.product_id,
                    variant_id=l.variant_id,
                    quantity=l.quantity + quantity,
                    unit_price=l.unit_price,
                    title=l.title,
                    selected_options=l.selected_options,
                )
                if l.line_id == line_match.line_id
                else l
                for l in existing_lines
            ]
            modified_line_id = line_match.line_id
        else:
            line_id = f"line_{uuid.uuid4().hex[:8]}"
            new_line = CartLine(
                line_id=line_id,
                product_id=product_id,
                variant_id=chosen_variant_id,
                quantity=quantity,
                unit_price=unit_price,
                title=title,
                selected_options=selected_options,
            )
            updated_lines = [*existing_lines, new_line]
            modified_line_id = line_id

        updated_cart = Cart(
            cart_id=cart.cart_id,
            session_id=session_id,
            lines=tuple(updated_lines),
            currency=cart.currency,
            updated_at=datetime.now(UTC),
        )
        self._carts[session_id] = updated_cart
        return CartUpdateResult(
            cart_id=updated_cart.cart_id,
            action="add",
            modified_line_id=modified_line_id,
            cart=updated_cart,
        )

    async def remove_from_cart(self, session_id: str, line_id: str) -> CartUpdateResult:
        cart = await self.get_cart(session_id)
        filtered_lines = tuple(line for line in cart.lines if line.line_id != line_id)
        updated_cart = Cart(
            cart_id=cart.cart_id,
            session_id=session_id,
            lines=filtered_lines,
            currency=cart.currency,
            updated_at=datetime.now(UTC),
        )
        self._carts[session_id] = updated_cart
        return CartUpdateResult(
            cart_id=updated_cart.cart_id,
            action="remove",
            modified_line_id=line_id,
            cart=updated_cart,
        )

    async def update_cart_item(
        self, session_id: str, line_id: str, quantity: int
    ) -> CartUpdateResult:
        if quantity <= 0:
            return await self.remove_from_cart(session_id, line_id)

        cart = await self.get_cart(session_id)
        updated_lines: list[CartLine] = []
        modified = False
        for line in cart.lines:
            if line.line_id == line_id:
                updated_lines.append(
                    CartLine(
                        line_id=line.line_id,
                        product_id=line.product_id,
                        variant_id=line.variant_id,
                        quantity=quantity,
                        unit_price=line.unit_price,
                        title=line.title,
                        selected_options=line.selected_options,
                    )
                )
                modified = True
            else:
                updated_lines.append(line)

        updated_cart = Cart(
            cart_id=cart.cart_id,
            session_id=session_id,
            lines=tuple(updated_lines),
            currency=cart.currency,
            updated_at=datetime.now(UTC),
        )
        self._carts[session_id] = updated_cart
        return CartUpdateResult(
            cart_id=updated_cart.cart_id,
            action="update",
            modified_line_id=line_id if modified else None,
            cart=updated_cart,
        )

    @staticmethod
    def _default_products() -> list[Product]:
        return [
            Product(
                product_id="prod_runner_01",
                title="AeroStride Carbon Running Shoes",
                description="High-cushion marathon shoes with responsive carbon-fiber plate.",
                base_price=180.0,
                category="footwear",
                in_stock=True,
                tags=("running", "marathon", "lightweight"),
                variants=(),
            ),
            Product(
                product_id="prod_tee_01",
                title="Merino Trail Breathable T-Shirt",
                description="Ultra-fine 100% merino wool shirt for hiking and daily comfort.",
                base_price=65.0,
                category="apparel",
                in_stock=True,
                tags=("wool", "breathable", "outdoor"),
                variants=(),
            ),
        ]

    @staticmethod
    def _default_orders() -> list[Order]:
        return [
            Order(
                order_id="ord_9901",
                customer_id="cust_001",
                status=OrderStatus.DELIVERED,
                total_amount=180.0,
                currency="USD",
                lines=(
                    OrderLine(
                        line_id="oline_1",
                        product_id="prod_runner_01",
                        variant_id=None,
                        title="AeroStride Carbon Running Shoes",
                        quantity=1,
                        price=180.0,
                    ),
                ),
                created_at=datetime(2026, 8, 15, 10, 30),
                tracking_number="TRK-883921",
            )
        ]

    @staticmethod
    def _default_policies() -> list[Policy]:
        return [
            Policy(
                policy_id="pol_returns",
                category=PolicyCategory.RETURNS,
                title="30-Day Hassle-Free Returns",
                content_markdown="Customers may return unworn items in original packaging within 30 days of delivery.",
            ),
            Policy(
                policy_id="pol_shipping",
                category=PolicyCategory.SHIPPING,
                title="Standard & Express Shipping",
                content_markdown="Orders over $50 qualify for free standard ground shipping (3-5 business days).",
            ),
        ]


class InMemoryMerchantBackend(MerchantBackendProtocol):
    """In-memory Merchant backend implementation."""

    def __init__(
        self,
        listings: list[Listing] | None = None,
        summary: PerformanceSummary | None = None,
        pricing_contexts: dict[str, PricingContext] | None = None,
        inventory_alerts: list[InventoryAlert] | None = None,
    ) -> None:
        self._listings: dict[str, Listing] = {
            item.listing_id: item for item in (listings or self._default_listings())
        }
        self._summary = summary or self._default_summary()
        self._pricing_contexts = pricing_contexts or self._default_pricing()
        self._inventory_alerts = list(inventory_alerts or self._default_alerts())
        self._staged_changes: dict[str, StagedChange] = {}

    @property
    def _performance_summary(self) -> PerformanceSummary:
        return self._summary

    @_performance_summary.setter
    def _performance_summary(self, val: PerformanceSummary) -> None:
        self._summary = val

    async def get_performance_summary(self, time_range: str = "last_7d") -> PerformanceSummary:
        return self._summary

    async def get_listing(self, listing_id: str) -> Listing | None:
        return self._listings.get(listing_id)

    async def list_listings(self) -> list[Listing]:
        """List all current merchant listings."""
        return list(self._listings.values())

    async def stage_listing_change(
        self,
        listing_id: str,
        change_type: ChangeType,
        proposed_values: tuple[tuple[str, str], ...],
    ) -> StagedChange:
        if listing_id not in self._listings:
            raise ChangeNotApplicable(f"Listing {listing_id} does not exist.")

        change_id = f"stg_{uuid.uuid4().hex[:8]}"
        staged = StagedChange(
            change_id=change_id,
            listing_id=listing_id,
            change_type=change_type,
            proposed_values=proposed_values,
            staged_at=datetime.now(UTC),
            applied=False,
        )
        self._staged_changes[change_id] = staged
        return staged

    async def apply_staged_change(self, change_id: str) -> ApplyResult:
        staged = self._staged_changes.get(change_id)
        if not staged or staged.applied:
            raise InvalidStagedChange(f"Staged change {change_id} is missing or already applied.")

        listing = self._listings.get(staged.listing_id)
        if not listing:
            raise ChangeNotApplicable(f"Listing {staged.listing_id} no longer exists.")

        vals = dict(staged.proposed_values)
        updated_price = float(vals["price"]) if "price" in vals else listing.price
        updated_stock = (
            int(vals["inventory_count"]) if "inventory_count" in vals else listing.inventory_count
        )
        updated_title = vals.get("title", listing.title)

        updated_listing = Listing(
            listing_id=listing.listing_id,
            title=updated_title,
            description=listing.description,
            price=updated_price,
            inventory_count=updated_stock,
            status=listing.status,
            category=listing.category,
            tags=listing.tags,
        )
        self._listings[listing.listing_id] = updated_listing
        self._staged_changes[change_id] = StagedChange(
            change_id=staged.change_id,
            listing_id=staged.listing_id,
            change_type=staged.change_type,
            proposed_values=staged.proposed_values,
            staged_at=staged.staged_at,
            applied=True,
        )

        return ApplyResult(
            change_id=change_id,
            listing_id=listing.listing_id,
            success=True,
            message="Change successfully applied to live catalog.",
            audit_id=f"audit_{uuid.uuid4().hex[:8]}",
        )

    async def get_pricing_context(self, listing_id: str) -> PricingContext:
        listing = self._listings.get(listing_id)
        if listing_id in self._pricing_contexts:
            ctx = self._pricing_contexts[listing_id]
            if listing and listing.price != ctx.current_price:
                return PricingContext(
                    listing_id=listing_id,
                    current_price=listing.price,
                    cost=listing.price * 0.4,
                    margin_pct=ctx.margin_pct,
                    min_allowed_price=ctx.min_allowed_price,
                    max_allowed_price=ctx.max_allowed_price,
                    competitors=ctx.competitors,
                )
            return ctx
        current_price = listing.price if listing else 100.0
        return PricingContext(
            listing_id=listing_id,
            current_price=current_price,
            cost=current_price * 0.4,
            margin_pct=60.0,
            min_allowed_price=current_price * 0.7,
            max_allowed_price=current_price * 1.5,
            competitors=(),
        )

    async def get_inventory_alerts(
        self, min_severity: str = "warning"
    ) -> list[InventoryAlert]:
        severities = [InventoryAlertSeverity.INFO, InventoryAlertSeverity.WARNING, InventoryAlertSeverity.CRITICAL]
        min_idx = 1
        if min_severity == "info":
            min_idx = 0
        elif min_severity == "critical":
            min_idx = 2
        allowed = set(severities[min_idx:])
        return [alert for alert in self._inventory_alerts if alert.severity in allowed]

    @staticmethod
    def _default_listings() -> list[Listing]:
        return [
            Listing(
                listing_id="list_001",
                title="AeroStride Carbon Running Shoes",
                description="Marathon racing shoes with carbon plate.",
                price=180.0,
                inventory_count=24,
                status=ListingStatus.ACTIVE,
                category="footwear",
                tags=("running", "bestseller"),
            ),
            Listing(
                listing_id="list_002",
                title="Merino Trail Breathable T-Shirt",
                description="100% merino outdoor shirt.",
                price=65.0,
                inventory_count=4,
                status=ListingStatus.ACTIVE,
                category="apparel",
                tags=("outdoor", "low_stock"),
            ),
        ]

    @staticmethod
    def _default_summary() -> PerformanceSummary:
        return PerformanceSummary(
            time_range="last_7d",
            gmv=12450.0,
            order_count=86,
            conversion_rate=3.4,
            average_order_value=144.76,
            top_products=(
                TopProductMetric(
                    product_id="prod_runner_01",
                    title="AeroStride Carbon Running Shoes",
                    units_sold=42,
                    revenue=7560.0,
                ),
            ),
            critical_alert_count=1,
        )

    @staticmethod
    def _default_pricing() -> dict[str, PricingContext]:
        return {
            "list_001": PricingContext(
                listing_id="list_001",
                current_price=180.0,
                cost=72.0,
                margin_pct=60.0,
                min_allowed_price=140.0,
                max_allowed_price=220.0,
                competitors=(),
            )
        }

    @staticmethod
    def _default_alerts() -> list[InventoryAlert]:
        return [
            InventoryAlert(
                listing_id="list_002",
                title="Merino Trail Breathable T-Shirt",
                current_stock=4,
                safety_stock=15,
                days_of_supply=1.8,
                severity=InventoryAlertSeverity.CRITICAL,
            )
        ]

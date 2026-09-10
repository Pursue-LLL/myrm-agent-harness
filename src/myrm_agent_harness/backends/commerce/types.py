"""Commerce domain type definitions and DTOs.

[INPUT]
- (none)

[OUTPUT]
- CommerceRole: 商业会话角色枚举 (STOREFRONT, MERCHANT)
- Money: 金额对象
- VariantOption: 变体多规格选项
- ProductVariant: 商品变体规格
- Product: 商品详情与目录项
- ProductFilter: 目录检索过滤器
- CartLine: 购物车条目
- Cart: 购物车实体
- CartUpdateResult: 购物车变更操作结果
- OrderStatus: 订单状态枚举
- OrderLine: 订单项
- Order: 历史订单
- PolicyCategory: 政策分类枚举
- Policy: 商店条款与退换政策
- PolicySearchResult: 政策匹配结果
- TopProductMetric: 畅销商品指标
- PerformanceSummary: 商家端大盘经营表现摘要
- ListingStatus: 商品刊登状态枚举
- Listing: 商家端商品刊登实体
- ChangeType: 暂存变更类型枚举
- StagedChange: 待审核暂存变更
- ApplyResult: 变更生效结果
- CompetitorPrice: 竞品价格信息
- PricingContext: 定价与利润率上下文
- InventoryAlertSeverity: 库存告警级别枚举
- InventoryAlert: 库存与缺货预警
- ShoppingSessionState: C端消费者会话状态隔离实体
- MerchantSessionState: B端商家运营会话状态隔离实体

[POS]
Domain type definitions for dual-role commerce agent architectures.
Covers Storefront (C-end) shopper journeys and Merchant (B-end) back-office operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class CommerceRole(str, Enum):
    """Commerce session role."""

    STOREFRONT = "storefront"
    MERCHANT = "merchant"


@dataclass(frozen=True, slots=True)
class Money:
    """Monetary amount with currency."""

    amount: float
    currency: str = "USD"


@dataclass(frozen=True, slots=True)
class VariantOption:
    """Option selector for a product variant (e.g. Size=L, Color=Black)."""

    name: str
    value: str


@dataclass(frozen=True, slots=True)
class ProductVariant:
    """Specific variant of a product."""

    variant_id: str
    title: str
    price: float
    sku: str = ""
    in_stock: bool = True
    inventory_quantity: int = 0
    options: tuple[VariantOption, ...] = ()


@dataclass(frozen=True, slots=True)
class ProductFilter:
    """Deterministic filter criteria for catalog search."""

    category: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    in_stock_only: bool = False
    tags: tuple[str, ...] = ()

    @property
    def in_stock(self) -> bool:
        """Alias for in_stock_only."""
        return self.in_stock_only


@dataclass(frozen=True, slots=True)
class Product:
    """Catalog product representation."""

    product_id: str
    title: str
    description: str
    base_price: float
    category: str
    in_stock: bool = True
    tags: tuple[str, ...] = ()
    variants: tuple[ProductVariant, ...] = ()
    policies: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return self.product_id


@dataclass(frozen=True, slots=True)
class CartLine:
    """Single item line in a shopping cart."""

    line_id: str
    product_id: str
    variant_id: str | None
    quantity: int
    unit_price: float
    title: str = ""
    selected_options: tuple[VariantOption, ...] = ()


@dataclass(frozen=True, slots=True)
class Cart:
    """Customer shopping cart."""

    cart_id: str = "default_cart"
    session_id: str = "default_session"
    lines: tuple[CartLine, ...] = ()
    currency: str = "USD"
    updated_at: datetime | None = None

    @property
    def subtotal(self) -> float:
        """Calculate total amount before discounts and taxes."""
        return sum(line.unit_price * line.quantity for line in self.lines)

    @property
    def total_amount(self) -> float:
        """Alias for subtotal."""
        return self.subtotal

    @property
    def total_quantity(self) -> int:
        """Total number of items in cart."""
        return sum(line.quantity for line in self.lines)


@dataclass(frozen=True, slots=True)
class CartUpdateResult:
    """Result of modifying a cart."""

    cart_id: str
    action: str  # add, remove, update, clear
    modified_line_id: str | None
    cart: Cart


class OrderStatus(str, Enum):
    """Order fulfillment status."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


@dataclass(frozen=True, slots=True)
class OrderLine:
    """Line item in an order."""

    line_id: str
    product_id: str
    variant_id: str | None
    title: str
    quantity: int
    price: float


@dataclass(frozen=True, slots=True)
class Order:
    """Customer historical order."""

    order_id: str
    customer_id: str
    status: OrderStatus
    total_amount: float
    currency: str
    lines: tuple[OrderLine, ...]
    created_at: datetime
    tracking_number: str | None = None


class PolicyCategory(str, Enum):
    """Store policy category."""

    RETURNS = "returns"
    SHIPPING = "shipping"
    WARRANTY = "warranty"
    PRIVACY = "privacy"
    TERMS = "terms"
    CANCELLATIONS = "cancellations"
    PAYMENT = "payment"


@dataclass(frozen=True, slots=True)
class Policy:
    """Store policy statement."""

    policy_id: str
    category: PolicyCategory
    title: str
    content_markdown: str

    @property
    def content(self) -> str:
        return self.content_markdown


@dataclass(frozen=True, slots=True)
class PolicySearchResult:
    """Matched policy result with excerpt."""

    policy_id: str
    title: str
    category: PolicyCategory
    excerpt: str
    score: float

    @property
    def content_markdown(self) -> str:
        return self.excerpt


# --- B-end Merchant Types ---


@dataclass(frozen=True, slots=True)
class TopProductMetric:
    """High-performing product summary."""

    product_id: str
    title: str
    units_sold: int
    revenue: float


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    """Store performance dashboard summary for merchants."""

    time_range: str
    gmv: float
    order_count: int
    conversion_rate: float
    average_order_value: float
    top_products: tuple[TopProductMetric, ...] = ()
    critical_alert_count: int = 0

    @property
    def gmv_amount(self) -> float:
        """Alias for gmv."""
        return self.gmv

    @property
    def total_gmv(self) -> float:
        """Alias for gmv."""
        return self.gmv


class ListingStatus(str, Enum):
    """Listing catalog publication status."""

    ACTIVE = "active"
    DRAFT = "draft"
    PAUSED = "paused"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class Listing:
    """Merchant product listing."""

    listing_id: str
    title: str
    description: str
    price: float
    inventory_count: int
    status: ListingStatus
    category: str
    tags: tuple[str, ...] = ()
    product_id: str | None = None
    merchant_id: str | None = None
    product: Product | None = None

    @property
    def current_price(self) -> float:
        return self.price


class ChangeType(str, Enum):
    """Type of staged change proposal."""

    PRICE_UPDATE = "price_update"
    CONTENT_UPDATE = "content_update"
    RESTOCK = "restock"
    PROMOTION = "promotion"


@dataclass(frozen=True, slots=True)
class StagedChange:
    """Staged proposal awaiting review or confirmation."""

    change_id: str
    listing_id: str
    change_type: ChangeType
    proposed_values: tuple[tuple[str, str], ...]
    staged_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    applied: bool = False


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Result of applying a staged change."""

    change_id: str
    listing_id: str
    success: bool
    message: str
    audit_id: str


@dataclass(frozen=True, slots=True)
class CompetitorPrice:
    """Market competitor pricing data point."""

    competitor_name: str
    price: float
    url: str | None = None


@dataclass(frozen=True, slots=True)
class PricingContext:
    """Pricing guidance and financial constraints."""

    listing_id: str
    current_price: float = 0.0
    cost: float = 0.0
    margin_pct: float = 0.0
    min_allowed_price: float = 0.0
    max_allowed_price: float = 0.0
    competitors: tuple[CompetitorPrice, ...] = ()
    floor_price: float | None = None
    ceiling_price: float | None = None
    recommended_price: float | None = None

    @property
    def effective_floor_price(self) -> float:
        return self.floor_price if self.floor_price is not None else self.min_allowed_price

    @property
    def effective_ceiling_price(self) -> float:
        return self.ceiling_price if self.ceiling_price is not None else self.max_allowed_price


class InventoryAlertSeverity(str, Enum):
    """Severity of inventory health alert."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class InventoryAlert:
    """Inventory deficiency warning."""

    listing_id: str
    title: str
    current_stock: int
    safety_stock: int
    days_of_supply: float
    severity: InventoryAlertSeverity


# --- Session State Isolation ---


@dataclass(frozen=True, slots=True)
class ShoppingSessionState:
    """Isolated state for consumer storefront shopping journeys."""

    session_id: str
    customer_id: str | None = None
    active_cart_id: str | None = None
    role: CommerceRole = CommerceRole.STOREFRONT
    last_viewed_product_ids: tuple[str, ...] = ()
    preferences: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class MerchantSessionState:
    """Isolated state for merchant back-office management journeys."""

    session_id: str
    merchant_id: str = ""
    operator_id: str = ""
    roles: tuple[str, ...] = ()
    role: CommerceRole = CommerceRole.MERCHANT
    active_listing_id: str | None = None
    staged_change_ids: tuple[str, ...] = ()
    authorized_permissions: tuple[str, ...] = ("read_performance", "stage_changes")

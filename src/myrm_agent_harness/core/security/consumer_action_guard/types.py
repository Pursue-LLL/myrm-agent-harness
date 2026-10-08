from dataclasses import dataclass, field
from enum import StrEnum


class ConsumerActionTypeEnum(StrEnum):
    """Real-world consumer action categories."""

    FOOD_DELIVERY = "FOOD_DELIVERY"
    GROCERY_PURCHASE = "GROCERY_PURCHASE"
    RIDE_HAILING = "RIDE_HAILING"
    TICKETING = "TICKETING"
    UTILITY_BILL = "UTILITY_BILL"
    GENERAL_RETAIL = "GENERAL_RETAIL"


class ActionEvaluationVerdictEnum(StrEnum):
    """Evaluation verdict for consumer-grade actions."""

    ALLOW_AUTONOMOUS = "ALLOW_AUTONOMOUS"
    REQUIRES_HUMAN_CONFIRMATION = "REQUIRES_HUMAN_CONFIRMATION"
    VELOCITY_RATE_LIMITED = "VELOCITY_RATE_LIMITED"
    DAILY_BUDGET_EXCEEDED = "DAILY_BUDGET_EXCEEDED"
    UNTRUSTED_ADDRESS_BLOCKED = "UNTRUSTED_ADDRESS_BLOCKED"


@dataclass(frozen=True)
class ConsumerOrderSpec:
    """Specification of an outbound real-world consumer order or booking action."""

    order_id: str
    agent_id: str
    action_type: ConsumerActionTypeEnum
    item_name: str
    quantity: int
    unit_price: float
    total_amount: float
    recipient_name: str
    recipient_phone: str
    delivery_address: str
    merchant_id: str
    timestamp: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ConsumerGuardPolicy:
    """Configurable safety boundaries and ceilings for consumer actions."""

    max_item_quantity: int = 5
    max_single_action_amount: float = 100.0
    velocity_window_seconds: float = 900.0  # 15 minutes
    max_actions_per_window: int = 1
    daily_spend_ceiling: float = 200.0
    allowlisted_addresses: list[str] = field(default_factory=list)
    allowlisted_phones: list[str] = field(default_factory=list)
    allowlisted_merchants: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConsumerActionEvaluationResult:
    """Safety evaluation outcome on a consumer action."""

    is_allowed: bool
    verdict: ActionEvaluationVerdictEnum
    message: str
    requires_hitl: bool
    confirmation_card_summary: str | None = None


@dataclass(frozen=True)
class ConsumerGuardMetrics:
    """Telemetry counters for consumer protection guard."""

    total_evaluations: int
    autonomous_approvals: int
    hitl_confirmations_required: int
    velocity_blocks: int
    budget_exceeded_blocks: int
    address_blocks: int

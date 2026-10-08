
from .types import (
    ActionEvaluationVerdictEnum,
    ConsumerActionEvaluationResult,
    ConsumerGuardPolicy,
    ConsumerOrderSpec,
)


class QuantitySanityAsserter:
    """Evaluates real-world orders against common-sense quantity and single-order financial ceilings."""

    def evaluate_order(
        self,
        order: ConsumerOrderSpec,
        policy: ConsumerGuardPolicy,
    ) -> ConsumerActionEvaluationResult | None:
        """Check if order exceeds common-sense quantities or threshold limits requiring human confirmation."""
        reasons: list[str] = []

        if order.quantity > policy.max_item_quantity:
            reasons.append(
                f"Item count {order.quantity} exceeds common-sense ceiling of {policy.max_item_quantity} units."
            )

        if order.total_amount > policy.max_single_action_amount:
            reasons.append(
                f"Total cost ${order.total_amount:.2f} exceeds single autonomous action ceiling of ${policy.max_single_action_amount:.2f}."
            )

        if not reasons:
            return None

        # Assemble grandma-proof confirmation summary card
        card_summary = (
            f"⚠️ 【High-Volume / High-Value Action Confirmation Required】\n"
            f"Action: {order.action_type.value}\n"
            f"Item: {order.item_name} x {order.quantity}\n"
            f"Total to Pay: ${order.total_amount:.2f}\n"
            f"Recipient: {order.recipient_name} ({order.recipient_phone})\n"
            f"Delivery Address: {order.delivery_address}\n"
            f"Reason: {'; '.join(reasons)}"
        )

        return ConsumerActionEvaluationResult(
            is_allowed=False,
            verdict=ActionEvaluationVerdictEnum.REQUIRES_HUMAN_CONFIRMATION,
            message="; ".join(reasons),
            requires_hitl=True,
            confirmation_card_summary=card_summary,
        )

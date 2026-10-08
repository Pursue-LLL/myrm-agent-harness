
from .types import (
    ActionEvaluationVerdictEnum,
    ConsumerActionEvaluationResult,
    ConsumerGuardPolicy,
    ConsumerOrderSpec,
)


class AddressInvarianceGate:
    """Verifies physical address, recipient contact, and merchant invariance against whitelist."""

    def evaluate_order(
        self,
        order: ConsumerOrderSpec,
        policy: ConsumerGuardPolicy,
    ) -> ConsumerActionEvaluationResult | None:
        """Check if destination address, phone, or merchant violates allowed invariant sets."""
        violations: list[str] = []

        # 1. Address whitelist check (if configured)
        if policy.allowlisted_addresses:
            addr_matched = any(
                allowed.lower() in order.delivery_address.lower()
                for allowed in policy.allowlisted_addresses
            )
            if not addr_matched:
                violations.append(
                    f"Delivery address '{order.delivery_address}' not found in approved address whitelist."
                )

        # 2. Phone whitelist check (if configured)
        if policy.allowlisted_phones:
            phone_matched = any(
                allowed.strip() == order.recipient_phone.strip()
                for allowed in policy.allowlisted_phones
            )
            if not phone_matched:
                violations.append(
                    f"Recipient phone '{order.recipient_phone}' not found in trusted phone whitelist."
                )

        # 3. Merchant whitelist check (if configured)
        if policy.allowlisted_merchants:
            merchant_matched = any(
                allowed.lower() == order.merchant_id.lower()
                for allowed in policy.allowlisted_merchants
            )
            if not merchant_matched:
                violations.append(
                    f"Merchant '{order.merchant_id}' is not an authorized or verified merchant."
                )

        if not violations:
            return None

        return ConsumerActionEvaluationResult(
            is_allowed=False,
            verdict=ActionEvaluationVerdictEnum.UNTRUSTED_ADDRESS_BLOCKED,
            message="; ".join(violations),
            requires_hitl=True,
            confirmation_card_summary=(
                f"🚨 【Untrusted Destination Alert】\n"
                f"Attempted Delivery Address: {order.delivery_address}\n"
                f"Recipient Phone: {order.recipient_phone}\n"
                f"Merchant ID: {order.merchant_id}\n"
                f"Security Warning: {'; '.join(violations)}"
            ),
        )

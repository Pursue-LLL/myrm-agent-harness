"""Spend policy data structures and limits configuration.

[INPUT]
- None (pure dataclasses)

[OUTPUT]
- SpendPolicy: Configurable spending threshold and policy controls

[POS]
Harness-level pure configuration data structure for financial spend governance.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpendPolicy:
    """Policy rules governing autonomous and approved commercial spending."""

    enabled: bool = True
    per_action_cap: float = 50.0
    session_cap: float = 200.0
    base_currency: str = "USD"
    e_stop_active: bool = False
    enforce_digest_binding: bool = True
    monitored_tool_prefixes: tuple[str, ...] = field(
        default_factory=lambda: (
            "stripe_",
            "payment_",
            "charge_",
            "purchase_",
            "checkout_",
            "buy_",
            "order_",
        )
    )

    def is_action_capped(self, amount: float) -> bool:
        """Check if single spend exceeds per-action maximum."""
        if not self.enabled or self.e_stop_active:
            return True
        return amount > self.per_action_cap

    def is_session_capped(self, current_session_spent: float, additional_amount: float) -> bool:
        """Check if proposed spend would breach session budget."""
        if not self.enabled or self.e_stop_active:
            return True
        return (current_session_spent + additional_amount) > self.session_cap

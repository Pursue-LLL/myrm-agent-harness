import threading
import time

from .address_invariance_gate import AddressInvarianceGate
from .quantity_asserter import QuantitySanityAsserter
from .types import (
    ActionEvaluationVerdictEnum,
    ConsumerActionEvaluationResult,
    ConsumerGuardMetrics,
    ConsumerGuardPolicy,
    ConsumerOrderSpec,
)
from .velocity_limiter import ActionVelocityLimiter


class ConsumerRealWorldActionGuardSuite:
    """Unified consumer-grade safety suite preventing action explosion, runaway spending, and quantity insanity."""

    def __init__(self) -> None:
        self.quantity_asserter = QuantitySanityAsserter()
        self.velocity_limiter = ActionVelocityLimiter()
        self.address_gate = AddressInvarianceGate()

        self._lock = threading.Lock()
        # Key: agent_id -> list of (timestamp, amount) for rolling 24-hour daily spend tracking
        self._daily_spend_ledger: dict[str, list[tuple[float, float]]] = {}

        # Telemetry metrics counters
        self._total_evaluations: int = 0
        self._autonomous_approvals: int = 0
        self._hitl_confirmations: int = 0
        self._velocity_blocks: int = 0
        self._budget_blocks: int = 0
        self._address_blocks: int = 0

    def evaluate_order(
        self,
        order: ConsumerOrderSpec,
        policy: ConsumerGuardPolicy,
        current_time: float | None = None,
    ) -> ConsumerActionEvaluationResult:
        """Run comprehensive multi-layered physical guards on a real-world consumer order."""
        now = current_time if current_time is not None else time.time()

        with self._lock:
            self._total_evaluations += 1

        # Layer 1: Physical address and destination invariance check
        addr_res = self.address_gate.evaluate_order(order, policy)
        if addr_res is not None:
            with self._lock:
                self._address_blocks += 1
                self._hitl_confirmations += 1
            return addr_res

        # Layer 2: Quantity and single-action common-sense sanity check (Grandma-proof)
        sanity_res = self.quantity_asserter.evaluate_order(order, policy)
        if sanity_res is not None:
            with self._lock:
                self._hitl_confirmations += 1
            return sanity_res

        # Layer 3: Action velocity and burst rate limit check (15-min window)
        vel_res = self.velocity_limiter.check_velocity(
            agent_id=order.agent_id,
            action_type=order.action_type,
            policy=policy,
            current_time=now,
        )
        if vel_res is not None:
            with self._lock:
                self._velocity_blocks += 1
            return vel_res

        # Layer 4: Daily spending blast radius ceiling check (rolling 24 hours)
        rolling_24h_start = now - 86400.0
        with self._lock:
            records = self._daily_spend_ledger.get(order.agent_id, [])
            valid_records = [(ts, amt) for ts, amt in records if ts >= rolling_24h_start]
            self._daily_spend_ledger[order.agent_id] = valid_records
            current_spent = sum(amt for _, amt in valid_records)

        projected_spent = current_spent + order.total_amount
        if projected_spent > policy.daily_spend_ceiling:
            with self._lock:
                self._budget_blocks += 1
            return ConsumerActionEvaluationResult(
                is_allowed=False,
                verdict=ActionEvaluationVerdictEnum.DAILY_BUDGET_EXCEEDED,
                message=(
                    f"Daily living spend hard ceiling of ${policy.daily_spend_ceiling:.2f} exceeded. "
                    f"Current rolling 24h spend: ${current_spent:.2f}, attempted order: ${order.total_amount:.2f}."
                ),
                requires_hitl=True,
                confirmation_card_summary=(
                    f"🛑 【Daily Budget Ceiling Reached】\n"
                    f"Daily Limit: ${policy.daily_spend_ceiling:.2f}\n"
                    f"Spent in Past 24h: ${current_spent:.2f}\n"
                    f"Attempted: ${order.total_amount:.2f} for {order.item_name}\n"
                    f"Over-budget orders require manual confirmation to prevent debt."
                ),
            )

        # All layers passed: Allow autonomous execution
        with self._lock:
            self._autonomous_approvals += 1

        return ConsumerActionEvaluationResult(
            is_allowed=True,
            verdict=ActionEvaluationVerdictEnum.ALLOW_AUTONOMOUS,
            message="Consumer order satisfies all safety invariant guardrails.",
            requires_hitl=False,
        )

    def confirm_and_record_order(
        self,
        order: ConsumerOrderSpec,
        current_time: float | None = None,
    ) -> None:
        """Record an approved or human-confirmed order into daily spend ledger and velocity limiter."""
        now = current_time if current_time is not None else time.time()

        # Update velocity bucket
        self.velocity_limiter.record_action(
            agent_id=order.agent_id,
            action_type=order.action_type,
            current_time=now,
        )

        # Update daily spend ledger
        with self._lock:
            if order.agent_id not in self._daily_spend_ledger:
                self._daily_spend_ledger[order.agent_id] = []
            self._daily_spend_ledger[order.agent_id].append((now, order.total_amount))

    def get_agent_daily_spent(
        self,
        agent_id: str,
        current_time: float | None = None,
    ) -> float:
        """Get total spent in the rolling 24-hour window for an agent."""
        now = current_time if current_time is not None else time.time()
        rolling_24h_start = now - 86400.0

        with self._lock:
            records = self._daily_spend_ledger.get(agent_id, [])
            valid_records = [(ts, amt) for ts, amt in records if ts >= rolling_24h_start]
            self._daily_spend_ledger[agent_id] = valid_records
            return sum(amt for _, amt in valid_records)

    def get_metrics(self) -> ConsumerGuardMetrics:
        """Retrieve telemetry metrics for consumer action protection."""
        with self._lock:
            return ConsumerGuardMetrics(
                total_evaluations=self._total_evaluations,
                autonomous_approvals=self._autonomous_approvals,
                hitl_confirmations_required=self._hitl_confirmations,
                velocity_blocks=self._velocity_blocks,
                budget_exceeded_blocks=self._budget_blocks,
                address_blocks=self._address_blocks,
            )

    def reset(self, agent_id: str | None = None) -> None:
        """Reset velocity and spend records for an agent or all agents."""
        self.velocity_limiter.reset(agent_id=agent_id)
        with self._lock:
            if agent_id is None:
                self._daily_spend_ledger.clear()
            else:
                self._daily_spend_ledger.pop(agent_id, None)

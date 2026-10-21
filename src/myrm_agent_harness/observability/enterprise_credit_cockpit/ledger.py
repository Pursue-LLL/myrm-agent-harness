"""[INPUT] Credit transactions, actor identities, data scopes, and risk signals.
[OUTPUT] In-memory thread-safe enterprise ledger managing credit pool and unified audit chains.
[POS] myrm_agent_harness.observability.enterprise_credit_cockpit.ledger

Provides the thread-safe EnterpriseCreditRiskLedger collecting unified audit chains
(actor - time - data - risk) and monitoring credit utilization across product surfaces.
"""

from collections import deque
import threading
import uuid

from .models import (
    CreditPoolAllocation,
    CreditRiskAuditRecord,
    EnterpriseCockpitSnapshot,
    PolicyVerdict,
    RiskBehaviorType,
    RiskLevel,
)


class EnterpriseCreditRiskLedger:
    """Thread-safe ledger managing unified enterprise credit quotas and risk audit trails."""

    DEFAULT_QUOTA: float = 100000.0
    DEFAULT_WARNING_PCT: float = 80.0

    def __init__(self, total_quota: float = DEFAULT_QUOTA, max_audit_history: int = 200) -> None:
        self._lock = threading.Lock()
        self._total_credit_quota = max(1.0, float(total_quota))
        self._warning_threshold_pct = float(self.DEFAULT_WARNING_PCT)
        self._total_credit_spent: float = 0.0
        self._max_audit_history = max(20, max_audit_history)

        self._surface_credit: dict[str, float] = {
            "webui": 0.0,
            "desktop": 0.0,
            "cloud_sandbox": 0.0,
            "mobile": 0.0,
        }
        self._surface_requests: dict[str, int] = {
            "webui": 0,
            "desktop": 0,
            "cloud_sandbox": 0,
            "mobile": 0,
        }

        self._audit_records: deque[CreditRiskAuditRecord] = deque(maxlen=self._max_audit_history)
        self._risk_event_count: int = 0
        self._blocked_count: int = 0

    def configure_quota(self, total_quota: float, warning_threshold_pct: float = 80.0) -> None:
        """Update credit pool total quota and warning threshold."""
        with self._lock:
            self._total_credit_quota = max(1.0, float(total_quota))
            self._warning_threshold_pct = min(100.0, max(1.0, float(warning_threshold_pct)))

    def record_transaction(
        self,
        actor_id: str,
        product_surface: str,
        interaction_summary: str,
        data_object_scope: str,
        credit_consumed: float,
        risk_level: RiskLevel | str = RiskLevel.NONE,
        risk_behavior: RiskBehaviorType | str = RiskBehaviorType.NONE,
        policy_verdict: PolicyVerdict | str = PolicyVerdict.ALLOW,
    ) -> CreditRiskAuditRecord:
        """Record a single credit transaction linked with actor, data scope, and risk evaluation."""
        resolved_risk_level: RiskLevel
        if isinstance(risk_level, RiskLevel):
            resolved_risk_level = risk_level
        else:
            try:
                resolved_risk_level = RiskLevel(risk_level.upper())
            except ValueError:
                resolved_risk_level = RiskLevel.NONE

        resolved_behavior: RiskBehaviorType
        if isinstance(risk_behavior, RiskBehaviorType):
            resolved_behavior = risk_behavior
        else:
            try:
                resolved_behavior = RiskBehaviorType(risk_behavior.upper())
            except ValueError:
                resolved_behavior = RiskBehaviorType.NONE

        resolved_verdict: PolicyVerdict
        if isinstance(policy_verdict, PolicyVerdict):
            resolved_verdict = policy_verdict
        else:
            try:
                resolved_verdict = PolicyVerdict(policy_verdict.upper())
            except ValueError:
                resolved_verdict = PolicyVerdict.ALLOW

        safe_credit = max(0.0, float(credit_consumed))
        surface_key = product_surface.strip().lower() or "default"
        record_id = f"aud_{uuid.uuid4().hex[:12]}"

        record = CreditRiskAuditRecord(
            record_id=record_id,
            actor_id=actor_id.strip() or "anonymous",
            product_surface=surface_key,
            interaction_summary=interaction_summary.strip() or "N/A",
            data_object_scope=data_object_scope.strip() or "general",
            credit_consumed=safe_credit,
            risk_level=resolved_risk_level,
            risk_behavior=resolved_behavior,
            policy_verdict=resolved_verdict,
        )

        with self._lock:
            self._total_credit_spent += safe_credit
            self._surface_credit[surface_key] = self._surface_credit.get(surface_key, 0.0) + safe_credit
            self._surface_requests[surface_key] = self._surface_requests.get(surface_key, 0) + 1
            self._audit_records.append(record)

            if resolved_risk_level != RiskLevel.NONE:
                self._risk_event_count += 1
            if resolved_verdict == PolicyVerdict.BLOCKED:
                self._blocked_count += 1

        return record

    def get_cockpit_snapshot(self) -> EnterpriseCockpitSnapshot:
        """Produce an immutable snapshot of current enterprise credit and risk status."""
        with self._lock:
            total_quota = self._total_credit_quota
            spent = self._total_credit_spent
            available = max(0.0, total_quota - spent)
            utilization = round((spent / total_quota) * 100.0, 2) if total_quota > 0 else 0.0
            is_breached = spent >= total_quota

            allocations: list[CreditPoolAllocation] = []
            for surf, surf_spent in sorted(self._surface_credit.items()):
                reqs = self._surface_requests.get(surf, 0)
                allocations.append(
                    CreditPoolAllocation(
                        surface_name=surf,
                        credit_spent=round(surf_spent, 2),
                        request_count=reqs,
                    )
                )

            return EnterpriseCockpitSnapshot(
                total_credit_quota=round(total_quota, 2),
                total_credit_spent=round(spent, 2),
                available_credit=round(available, 2),
                utilization_pct=utilization,
                is_quota_breached=is_breached,
                warning_threshold_pct=self._warning_threshold_pct,
                total_audit_records=len(self._audit_records),
                risk_event_count=self._risk_event_count,
                blocked_count=self._blocked_count,
                allocations_by_surface=tuple(allocations),
                recent_audit_records=tuple(self._audit_records),
            )

    def filter_audit_records(
        self,
        actor_id: str | None = None,
        risk_level: RiskLevel | str | None = None,
        surface: str | None = None,
        limit: int = 50,
    ) -> list[CreditRiskAuditRecord]:
        """Query audit records with specific filters."""
        target_risk: RiskLevel | None = None
        if risk_level is not None:
            if isinstance(risk_level, RiskLevel):
                target_risk = risk_level
            else:
                try:
                    target_risk = RiskLevel(risk_level.upper())
                except ValueError:
                    target_risk = None

        with self._lock:
            results: list[CreditRiskAuditRecord] = []
            for record in reversed(self._audit_records):
                if actor_id and record.actor_id != actor_id:
                    continue
                if target_risk and record.risk_level != target_risk:
                    continue
                if surface and record.product_surface != surface.strip().lower():
                    continue
                results.append(record)
                if len(results) >= limit:
                    break
            return results

    def reset(self) -> None:
        """Reset ledger counters and history."""
        with self._lock:
            self._total_credit_spent = 0.0
            self._surface_credit = {
                "webui": 0.0,
                "desktop": 0.0,
                "cloud_sandbox": 0.0,
                "mobile": 0.0,
            }
            self._surface_requests = {
                "webui": 0,
                "desktop": 0,
                "cloud_sandbox": 0,
                "mobile": 0,
            }
            self._audit_records.clear()
            self._risk_event_count = 0
            self._blocked_count = 0


# Process-level singleton instance
_default_ledger: EnterpriseCreditRiskLedger | None = None
_ledger_lock = threading.Lock()


def get_default_credit_risk_ledger() -> EnterpriseCreditRiskLedger:
    """Obtain or initialize the global default EnterpriseCreditRiskLedger."""
    global _default_ledger
    if _default_ledger is None:
        with _ledger_lock:
            if _default_ledger is None:
                _default_ledger = EnterpriseCreditRiskLedger()
    return _default_ledger

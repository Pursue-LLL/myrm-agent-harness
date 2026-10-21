"""
[INPUT]: Organization IDs, query labels, budget configurations, and token expenditure traces.
[OUTPUT]: SpendGovernorDecision verdicts, org summaries, and per-user IdentSpendAttribution records.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/org_spend_limit/spend_governor.py
"""

from collections import defaultdict
from datetime import datetime, timezone
import threading
from typing import Dict, List, Optional
import uuid

from .models import (
    BillingScope,
    GovernorAction,
    IdentSpendAttribution,
    OrgMonthlySpendRecord,
    QuerySpendLabel,
    SpendGovernorDecision,
    SpendLimitConfig,
    SpendSurface,
)


class OrgSharedAgentSpendGovernor:
    """
    Manages organization-wide monthly spending limits, query label attribution,
    and automatic circuit breaker brakes for team-shared AI agent deployments.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # org_id -> SpendLimitConfig
        self._configs: Dict[str, SpendLimitConfig] = {}
        # org_id -> float (current accumulated spend in USD)
        self._accumulated_spends: Dict[str, float] = defaultdict(float)
        # org_id -> list of OrgMonthlySpendRecord
        self._records: Dict[str, List[OrgMonthlySpendRecord]] = defaultdict(list)

    def configure_org_budget(self, config: SpendLimitConfig) -> None:
        with self._lock:
            self._configs[config.org_id] = config

    def get_config(self, org_id: str) -> SpendLimitConfig:
        with self._lock:
            if org_id not in self._configs:
                self._configs[org_id] = SpendLimitConfig(org_id=org_id)
            return self._configs[org_id]

    def pre_check_and_guard(
        self,
        org_id: str,
        estimated_cost_usd: float,
        label: QuerySpendLabel,
    ) -> SpendGovernorDecision:
        with self._lock:
            # 1. Direct Messages routed to personal accounts are bypassed from org budget
            if label.billing_scope == BillingScope.PERSONAL_DM:
                curr = self._accumulated_spends[org_id]
                return SpendGovernorDecision(
                    action=GovernorAction.ALLOW,
                    current_spend_usd=curr,
                    monthly_budget_usd=self.get_config(org_id).monthly_budget_usd,
                    utilization_pct=0.0,
                    reason="个人私聊会话已自动记入个人账单，不计入组织共享月度限额。",
                    is_blocked=False,
                )

            cfg = self.get_config(org_id)
            current_spend = self._accumulated_spends[org_id]
            projected = current_spend + max(0.0, estimated_cost_usd)
            utilization = round((projected / max(0.01, cfg.monthly_budget_usd)) * 100.0, 2)

            # 2. Hard block limit (100% threshold)
            if projected >= cfg.hard_block_limit_usd and cfg.is_circuit_breaker_enabled:
                return SpendGovernorDecision(
                    action=GovernorAction.CIRCUIT_BREAKER_BLOCKED,
                    current_spend_usd=current_spend,
                    monthly_budget_usd=cfg.monthly_budget_usd,
                    utilization_pct=utilization,
                    reason=(
                        f"组织月度支出已达 ${projected:.2f} (预算 ${cfg.monthly_budget_usd:.2f})，"
                        f"触碰 {utilization}% 硬限额熔断刹车，执行已安全挂起。"
                    ),
                    is_blocked=True,
                )

            # 3. Soft warn watermark (80% threshold)
            if utilization >= cfg.soft_warn_watermark_pct:
                return SpendGovernorDecision(
                    action=GovernorAction.WARN_APPROACHING,
                    current_spend_usd=current_spend,
                    monthly_budget_usd=cfg.monthly_budget_usd,
                    utilization_pct=utilization,
                    reason=(
                        f"组织月度支出水位已达 {utilization}%，接近 ${cfg.monthly_budget_usd:.2f} 限额，"
                        "已施加预警提示并顺畅放行。"
                    ),
                    is_blocked=False,
                )

            # 4. Standard healthy pass
            return SpendGovernorDecision(
                action=GovernorAction.ALLOW,
                current_spend_usd=current_spend,
                monthly_budget_usd=cfg.monthly_budget_usd,
                utilization_pct=utilization,
                reason="组织预算水位健康，已通过标签验证并顺畅放行。",
                is_blocked=False,
            )

    def record_spend(
        self,
        org_id: str,
        actual_tokens: int,
        actual_cost_usd: float,
        label: QuerySpendLabel,
    ) -> OrgMonthlySpendRecord:
        now_str = datetime.now(timezone.utc).isoformat()
        rec = OrgMonthlySpendRecord(
            record_id=f"rec-{uuid.uuid4().hex[:12]}",
            org_id=org_id,
            label=label,
            tokens_consumed=max(0, actual_tokens),
            cost_usd=max(0.0, actual_cost_usd),
            recorded_at=now_str,
        )

        with self._lock:
            # Only channel work billed to org increments org total spend
            if label.billing_scope == BillingScope.ORG_SHARED:
                self._accumulated_spends[org_id] += actual_cost_usd
            self._records[org_id].append(rec)

        return rec

    def get_user_attributions(self, org_id: str) -> List[IdentSpendAttribution]:
        with self._lock:
            records = list(self._records.get(org_id, []))

        # Group by requesting_user_id
        grouped: Dict[str, List[OrgMonthlySpendRecord]] = defaultdict(list)
        for r in records:
            grouped[r.label.requesting_user_id].append(r)

        results: List[IdentSpendAttribution] = []
        for user_id, items in grouped.items():
            calls_count = len(items)
            total_toks = sum(i.tokens_consumed for i in items)
            total_cost = round(sum(i.cost_usd for i in items), 4)

            # Breakdown by surface
            surface_cost: Dict[str, float] = defaultdict(float)
            for i in items:
                surface_cost[i.label.surface.value] += i.cost_usd

            # Find primary surface
            primary_surf = (
                max(surface_cost.keys(), key=lambda k: surface_cost[k])
                if surface_cost
                else SpendSurface.CHANNEL.value
            )

            results.append(
                IdentSpendAttribution(
                    requesting_user_id=user_id,
                    total_calls_count=calls_count,
                    total_tokens=total_toks,
                    total_spend_usd=total_cost,
                    surfaces_breakdown={k: round(v, 4) for k, v in surface_cost.items()},
                    primary_surface=primary_surf,
                )
            )

        # Sort descending by spend
        results.sort(key=lambda x: x.total_spend_usd, reverse=True)
        return results

    def get_org_summary(self, org_id: str) -> Dict[str, float]:
        with self._lock:
            cfg = self.get_config(org_id)
            current_spend = round(self._accumulated_spends[org_id], 4)
            records_count = len(self._records.get(org_id, []))
            budget = cfg.monthly_budget_usd
            remaining = round(max(0.0, budget - current_spend), 4)
            pct = round((current_spend / max(0.01, budget)) * 100.0, 2)

        return {
            "monthly_budget_usd": budget,
            "current_spend_usd": current_spend,
            "remaining_budget_usd": remaining,
            "utilization_pct": pct,
            "total_records_count": float(records_count),
        }

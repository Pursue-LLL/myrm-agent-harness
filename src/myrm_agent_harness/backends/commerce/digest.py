"""Commercial digest, proactive operational alerts, and headless diagnostic runner.

[INPUT]
- MerchantBackendProtocol, PerformanceSummary, InventoryAlert from myrm_agent_harness.backends.commerce

[OUTPUT]
- AttentionCategory: 关注项分类枚举
- AttentionSeverity: 关注项严重程度枚举
- KpiComparison: KPI 跨期对比与趋势结构体
- DigestAction: 一键快捷处置动作
- AttentionItem: 结构化单项关注与归因项
- CommercialDigestCard: 完整商业晨报卡片实体
- CommercialDigestRunner: 无头单轮经营参谋诊断运行时

[POS]
Proactive operational intelligence layer for merchants and store operators.
Eliminates passive reporting bottlenecks by generating actionable morning briefings headlessly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
import uuid

from myrm_agent_harness.backends.commerce.protocols import MerchantBackendProtocol
from myrm_agent_harness.backends.commerce.types import (
    InventoryAlert,
    InventoryAlertSeverity,
    PerformanceSummary,
)


class AttentionCategory(str, Enum):
    """Category of operational attention item."""

    INVENTORY = "inventory"
    PRICING = "pricing"
    PROMOTION = "promotion"
    CONVERSION = "conversion"
    COMPLIANCE = "compliance"
    ORDER = "order"


class AttentionSeverity(str, Enum):
    """Urgency level for attention items."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class KpiComparison:
    """Comparison of a core KPI against the prior period."""

    name: str
    current_value: float
    previous_value: float | None = None
    change_pct: float = 0.0
    trend: str = "flat"  # up, down, flat
    format_type: str = "number"  # currency, percentage, count, number


@dataclass(frozen=True, slots=True)
class DigestAction:
    """Actionable remediation shortcut attached to a digest item."""

    action_id: str
    label: str
    action_type: str
    target_id: str | None = None
    suggested_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """A prioritized anomaly or operational bottleneck requiring merchant review."""

    item_id: str
    title: str
    severity: AttentionSeverity
    category: AttentionCategory = AttentionCategory.INVENTORY
    metric_name: str = ""
    current_value: str = ""
    attribution: str = ""
    recommended_action: str = ""
    action_type: str = "quick_fix"
    related_listing_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CommercialDigestCard:
    """Complete structured briefing card rendered in WebUI or sent via channels."""

    digest_id: str
    store_name: str
    generated_at: datetime
    gmv: float = 0.0
    order_count: int = 0
    conversion_rate: float = 0.0
    average_order_value: float = 0.0
    currency: str = "USD"
    kpis: tuple[KpiComparison, ...] = ()
    attention_items: tuple[AttentionItem, ...] = ()
    actions: tuple[DigestAction, ...] = ()
    headline: str = "Today's Overview"
    summary_narrative: str = ""
    executive_summary: str = ""
    critical_alerts_count: int = 0

    def to_card_payload(self) -> dict[str, Any]:
        """Serialize digest for WebUI card rendering and JSON export."""
        return {
            "card_type": "commercial_digest",
            "component": "commercial_morning_digest",
            "digest_id": self.digest_id,
            "store_name": self.store_name,
            "generated_at": self.generated_at.isoformat(),
            "headline": self.headline,
            "executive_summary": self.executive_summary,
            "critical_count": self.critical_alerts_count,
            "currency": self.currency,
            "kpis": {
                "gmv": self.gmv,
                "order_count": self.order_count,
                "conversion_rate": self.conversion_rate,
                "average_order_value": self.average_order_value,
            },
            "attention_items": [
                {
                    "item_id": it.item_id,
                    "title": it.title,
                    "severity": it.severity.value,
                    "category": it.category.value,
                    "attribution": it.attribution,
                    "recommended_action": it.recommended_action,
                    "payload": it.payload,
                }
                for it in self.attention_items
            ],
            "actions": [
                {
                    "action_id": a.action_id,
                    "label": a.label,
                    "action_type": a.action_type,
                    "target_id": a.target_id,
                    "suggested_payload": a.suggested_payload,
                }
                for a in self.actions
            ],
        }

    def render_markdown(self) -> str:
        """Format digest into human-readable Markdown for external notifications."""
        lines = [
            f"# 📊 {self.store_name} Commercial Digest",
            f"**Generated**: {self.generated_at.strftime('%Y-%m-%d %H:%M UTC')} | **Status**: {self.headline}",
            "",
            f"> {self.executive_summary or self.summary_narrative}",
            "",
            "### 📈 Key Performance Indicators",
        ]
        for kpi in self.kpis:
            prev_str = (
                f" (vs {kpi.previous_value:,.2f})"
                if kpi.previous_value is not None
                else ""
            )
            lines.append(
                f"- **{kpi.name}**: {kpi.current_value:,.2f}{prev_str} [{kpi.trend} {kpi.change_pct:+.1f}%]"
            )

        lines.extend(
            [
                "",
                f"### 🚨 Needs Attention Today ({len(self.attention_items)} items, {self.critical_alerts_count} critical)",
            ]
        )
        if not self.attention_items:
            lines.append("✅ Operations smooth. No critical anomalies.")
        else:
            for item in self.attention_items:
                badge = "🔴" if item.severity == AttentionSeverity.CRITICAL else "🟡"
                lines.append(
                    f"- {badge} **[{item.category.value.upper()}]** {item.title}"
                )
                if item.attribution:
                    lines.append(f"  - *Attribution*: {item.attribution}")
                if item.recommended_action:
                    lines.append(f"  - *Action*: `{item.recommended_action}`")

        return "\n".join(lines)


class CommercialDigestRunner:
    """Headless single-turn diagnostic executor."""

    def __init__(
        self,
        backend: MerchantBackendProtocol | None = None,
        store_name: str = "Demo Store",
    ) -> None:
        self._backend = backend
        self.store_name = store_name

    def _compile_kpis(
        self,
        current: PerformanceSummary,
        previous: PerformanceSummary | None = None,
    ) -> tuple[KpiComparison, ...]:
        """Compute deltas, trends, and growth percentages across core metrics."""

        def calc_delta(curr: float, prev: float | None) -> tuple[float, str]:
            if prev is None or prev == 0.0:
                return 0.0, "flat"
            pct = ((curr - prev) / prev) * 100.0
            trend = "up" if pct > 0.01 else ("down" if pct < -0.01 else "flat")
            return pct, trend

        gmv_pct, gmv_trend = calc_delta(current.gmv, previous.gmv if previous else None)
        orders_pct, orders_trend = calc_delta(
            float(current.order_count),
            float(previous.order_count) if previous else None,
        )
        cr_pct, cr_trend = calc_delta(
            current.conversion_rate, previous.conversion_rate if previous else None
        )
        aov_pct, aov_trend = calc_delta(
            current.average_order_value,
            previous.average_order_value if previous else None,
        )

        return (
            KpiComparison(
                name="Gross Merchandise Volume (GMV)",
                current_value=current.gmv,
                previous_value=previous.gmv if previous else None,
                change_pct=gmv_pct,
                trend=gmv_trend,
                format_type="currency",
            ),
            KpiComparison(
                name="Total Orders",
                current_value=float(current.order_count),
                previous_value=float(previous.order_count) if previous else None,
                change_pct=orders_pct,
                trend=orders_trend,
                format_type="count",
            ),
            KpiComparison(
                name="Conversion Rate",
                current_value=current.conversion_rate,
                previous_value=previous.conversion_rate if previous else None,
                change_pct=cr_pct,
                trend=cr_trend,
                format_type="percentage",
            ),
            KpiComparison(
                name="Average Order Value (AOV)",
                current_value=current.average_order_value,
                previous_value=previous.average_order_value if previous else None,
                change_pct=aov_pct,
                trend=aov_trend,
                format_type="currency",
            ),
        )

    def _extract_attention_and_actions(
        self,
        summary: PerformanceSummary,
        alerts: list[InventoryAlert] | None = None,
    ) -> tuple[tuple[AttentionItem, ...], tuple[DigestAction, ...]]:
        """Map stock alerts and KPI dips into actionable attention items and shortcuts."""
        items: list[AttentionItem] = []
        actions: list[DigestAction] = []

        for alert in alerts or []:
            severity = (
                AttentionSeverity.CRITICAL
                if alert.severity == InventoryAlertSeverity.CRITICAL
                else AttentionSeverity.WARNING
            )
            item_id = f"item_{uuid.uuid4().hex[:8]}"
            items.append(
                AttentionItem(
                    item_id=item_id,
                    title=f"Low Stock Alert: {alert.title}",
                    severity=severity,
                    category=AttentionCategory.INVENTORY,
                    metric_name="inventory_stock",
                    current_value=str(alert.current_stock),
                    attribution=f"Current stock {alert.current_stock} below safety threshold {alert.safety_stock}",
                    recommended_action=f"紧急补货:建议向供应商发起补货工单，目标数量 {alert.safety_stock * 2}",
                    related_listing_id=alert.listing_id,
                    payload={
                        "listing_id": alert.listing_id,
                        "current_stock": alert.current_stock,
                    },
                )
            )
            actions.append(
                DigestAction(
                    action_id=f"act_restock_{alert.listing_id}",
                    label=f"Restock {alert.title}",
                    action_type="stage_restock",
                    target_id=alert.listing_id,
                    suggested_payload={
                        "listing_id": alert.listing_id,
                        "quantity": alert.safety_stock * 2,
                    },
                )
            )

        return tuple(items), tuple(actions)

    async def run_diagnostic(
        self,
        backend: MerchantBackendProtocol | None = None,
        time_range: str = "last_7d",
    ) -> CommercialDigestCard:
        """Run headless merchant diagnostic and produce CommercialDigestCard."""
        active_backend = backend or self._backend
        if active_backend is None:
            raise ValueError("No MerchantBackend provided to CommercialDigestRunner")

        summary = await active_backend.get_performance_summary(time_range=time_range)
        alerts = await active_backend.get_inventory_alerts()

        kpis = self._compile_kpis(summary)
        items, actions = self._extract_attention_and_actions(summary, alerts)
        critical_count = sum(
            1 for it in items if it.severity == AttentionSeverity.CRITICAL
        )

        headline = (
            "Today's Overview: Healthy Run"
            if critical_count == 0
            else f"Today's Overview: {critical_count} Critical Issues"
        )
        narrative = (
            f"Gross merchandise volume reached ${summary.gmv:,.2f} across {summary.order_count} orders "
            f"with a {summary.conversion_rate:.2f}% conversion rate."
        )
        executive_summary = (
            f"店铺经营整体平稳，GMV达到 ${summary.gmv:,.2f}。发现 {len(items)} 项需关注事项，其中 {critical_count} 项严重告警。"
            if critical_count == 0
            else f"店铺存在 {critical_count} 项严重库存告警，需紧急介入补货处理。"
        )

        return CommercialDigestCard(
            digest_id=f"dig_{uuid.uuid4().hex[:10]}",
            store_name=self.store_name,
            generated_at=datetime.now(UTC),
            gmv=summary.gmv,
            order_count=summary.order_count,
            conversion_rate=summary.conversion_rate,
            average_order_value=summary.average_order_value,
            kpis=kpis,
            attention_items=items,
            actions=actions,
            headline=headline,
            summary_narrative=narrative,
            executive_summary=executive_summary,
            critical_alerts_count=critical_count,
        )

    async def run_morning_audit(self) -> CommercialDigestCard:
        """Alias for standard morning audit."""
        return await self.run_diagnostic(time_range="last_7d")

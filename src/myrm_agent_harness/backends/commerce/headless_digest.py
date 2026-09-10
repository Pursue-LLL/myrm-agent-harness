"""Headless scheduled commerce morning digest and proactive event diagnostics suite.

[INPUT]
- MerchantBackendProtocol from myrm_agent_harness.backends.commerce.protocols
- InventoryAlert, InventoryAlertSeverity, PerformanceSummary from myrm_agent_harness.backends.commerce.types

[OUTPUT]
- DigestSeverity: ("info" | "warning" | "critical")
- DigestAttentionItem: 关注项实体 (item_id, title, severity, metric_name, current_value, attribution, recommended_action, payload)
- CommerceMorningDigest: 无头晨报完整快照 (digest_id, store_name, gmv, order_count, conversion_rate, average_order_value, critical_alerts_count, attention_items, executive_summary)
- HeadlessDigestRunner: 自动化无头晨会单轮诊断运行器
- format_digest_card_payload: 将 CommerceMorningDigest 转换为前端卡片渲染 Payload

[POS]
Powers automated store health diagnostics for scheduled background cron execution and omnichannel alerts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
import uuid

from myrm_agent_harness.backends.commerce.protocols import MerchantBackendProtocol
from myrm_agent_harness.backends.commerce.types import InventoryAlertSeverity


class DigestSeverity(str, Enum):
    """Urgency level for digest attention items."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class DigestAttentionItem:
    """Actionable attention item identified during headless store audit."""

    item_id: str
    title: str
    severity: DigestSeverity
    metric_name: str
    current_value: str
    attribution: str
    recommended_action: str
    action_type: str = "quick_fix"
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CommerceMorningDigest:
    """Structured headless commerce morning digest snapshot."""

    digest_id: str
    store_name: str
    generated_at: datetime
    gmv: float
    order_count: int
    conversion_rate: float
    average_order_value: float
    currency: str = "USD"
    attention_items: tuple[DigestAttentionItem, ...] = ()
    critical_alerts_count: int = 0
    executive_summary: str = ""


class HeadlessDigestRunner:
    """Headless diagnostic runner executing single-turn autonomous store health audits."""

    def __init__(
        self,
        backend: MerchantBackendProtocol,
        store_name: str = "Global Flagship Store",
    ) -> None:
        self.backend = backend
        self.store_name = store_name

    async def run_morning_audit(self, time_range: str = "last_7d") -> CommerceMorningDigest:
        """Run single-turn diagnosis over merchant backend data."""
        digest_id = f"dig_{uuid.uuid4().hex[:12]}"
        summary = await self.backend.get_performance_summary(time_range=time_range)
        inventory_alerts = await self.backend.get_inventory_alerts()

        attention_items: list[DigestAttentionItem] = []
        critical_count = 0

        for alert in inventory_alerts:
            if alert.severity == InventoryAlertSeverity.CRITICAL or alert.days_of_supply <= 2.0:
                critical_count += 1
                needed = max(alert.safety_stock * 2 - alert.current_stock, 10)
                attention_items.append(
                    DigestAttentionItem(
                        item_id=f"att_stock_{uuid.uuid4().hex[:6]}",
                        title=f"库存告急: {alert.title}",
                        severity=DigestSeverity.CRITICAL,
                        metric_name="inventory_stock",
                        current_value=f"{alert.current_stock} 件 (预估周转 {alert.days_of_supply:.1f} 天)",
                        attribution=f"当前库存已跌破安全库存线 ({alert.safety_stock} 件)",
                        recommended_action=f"建议立即发起紧急补货 {needed} 件，避免爆款缺货流失",
                        payload={"listing_id": alert.listing_id, "suggested_restock": needed},
                    )
                )
            elif alert.severity == InventoryAlertSeverity.WARNING:
                attention_items.append(
                    DigestAttentionItem(
                        item_id=f"att_stock_{uuid.uuid4().hex[:6]}",
                        title=f"低库存预警: {alert.title}",
                        severity=DigestSeverity.WARNING,
                        metric_name="inventory_stock",
                        current_value=f"{alert.current_stock} 件",
                        attribution=f"周转天数不足 ({alert.days_of_supply:.1f} 天)",
                        recommended_action="纳入下周常规补货计划",
                        payload={"listing_id": alert.listing_id},
                    )
                )

        if summary.conversion_rate < 0.015 and summary.order_count > 0:
            attention_items.append(
                DigestAttentionItem(
                    item_id=f"att_cr_{uuid.uuid4().hex[:6]}",
                    title="全店转化率波动风险",
                    severity=DigestSeverity.WARNING,
                    metric_name="conversion_rate",
                    current_value=f"{summary.conversion_rate:.2%}",
                    attribution="当前统计区间转化率低于行业基准线 (1.5%)",
                    recommended_action="建议核查商品详情页、首屏加载速度及优惠券承接情况",
                )
            )

        if critical_count > 0:
            exec_summary = (
                f"今日核心经营大盘平稳，但监测到 {critical_count} 项严重库存断货风险，"
                "请尽快审批建议补货工单。"
            )
        else:
            exec_summary = "今日核心经营大盘整体运行平稳，各项指标处于健康波动区间，无紧急阻断性风险。"

        return CommerceMorningDigest(
            digest_id=digest_id,
            store_name=self.store_name,
            generated_at=datetime.now(UTC),
            gmv=summary.gmv,
            order_count=summary.order_count,
            conversion_rate=summary.conversion_rate,
            average_order_value=summary.average_order_value,
            attention_items=tuple(attention_items),
            critical_alerts_count=critical_count,
            executive_summary=exec_summary,
        )


def format_digest_card_payload(digest: CommerceMorningDigest) -> dict[str, object]:
    """Helper converting CommerceMorningDigest into WebUI card payload."""
    return {
        "component": "commercial_morning_digest",
        "digest_id": digest.digest_id,
        "store_name": digest.store_name,
        "generated_at": digest.generated_at.isoformat(),
        "kpis": {
            "gmv": digest.gmv,
            "order_count": digest.order_count,
            "conversion_rate": digest.conversion_rate,
            "average_order_value": digest.average_order_value,
            "currency": digest.currency,
        },
        "critical_count": digest.critical_alerts_count,
        "executive_summary": digest.executive_summary,
        "attention_items": [
            {
                "item_id": it.item_id,
                "title": it.title,
                "severity": it.severity.value,
                "metric_name": it.metric_name,
                "current_value": it.current_value,
                "attribution": it.attribution,
                "recommended_action": it.recommended_action,
                "payload": it.payload,
            }
            for it in digest.attention_items
        ],
    }

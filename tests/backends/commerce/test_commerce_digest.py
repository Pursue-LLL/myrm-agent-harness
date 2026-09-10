"""Unit and integration tests for Scheduled Commercial Digest & Proactive Anomaly Suite.

[INPUT]
- myrm_agent_harness.backends.commerce::*

[OUTPUT]
- test_kpi_comparison_compilation: Verifies delta and trend calculation for GMV, orders, CR, AOV
- test_extract_attention_and_actions: Verifies stockout alert conversion to actionable remediation
- test_headless_diagnostic_runner_execution: Runs full CommercialDigestRunner on InMemoryMerchantBackend
- test_card_payload_and_markdown_rendering: Checks artifact card serialization and Markdown formatting

[POS]
Validates headless single-turn scheduled merchant digest generation.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.commerce.digest import (
    AttentionCategory,
    AttentionItem,
    AttentionSeverity,
    CommercialDigestCard,
    CommercialDigestRunner,
    DigestAction,
    KpiComparison,
)
from myrm_agent_harness.backends.commerce.memory_backend import InMemoryMerchantBackend
from myrm_agent_harness.backends.commerce.types import (
    InventoryAlert,
    InventoryAlertSeverity,
    PerformanceSummary,
    TopProductMetric,
)


@pytest.fixture
def current_summary() -> PerformanceSummary:
    return PerformanceSummary(
        time_range="last_7d",
        gmv=12500.0,
        order_count=100,
        conversion_rate=2.5,
        average_order_value=125.0,
        top_products=(
            TopProductMetric(product_id="p1", title="Carbon Shoe", units_sold=40, revenue=5000.0),
        ),
        critical_alert_count=1,
    )


@pytest.fixture
def previous_summary() -> PerformanceSummary:
    return PerformanceSummary(
        time_range="previous_7d",
        gmv=10000.0,
        order_count=80,
        conversion_rate=2.0,
        average_order_value=125.0,
        top_products=(),
        critical_alert_count=0,
    )


def test_kpi_comparison_compilation(
    current_summary: PerformanceSummary,
    previous_summary: PerformanceSummary,
) -> None:
    runner = CommercialDigestRunner(store_name="Athletics Hub")
    kpis = runner._compile_kpis(current_summary, previous_summary)

    kpi_map = {k.name: k for k in kpis}

    # GMV grew from 10k to 12.5k (+25%)
    gmv_kpi = kpi_map["Gross Merchandise Volume (GMV)"]
    assert gmv_kpi.current_value == 12500.0
    assert gmv_kpi.previous_value == 10000.0
    assert gmv_kpi.change_pct == pytest.approx(25.0)
    assert gmv_kpi.trend == "up"

    # Orders grew from 80 to 100 (+25%)
    orders_kpi = kpi_map["Total Orders"]
    assert orders_kpi.current_value == 100.0
    assert orders_kpi.change_pct == pytest.approx(25.0)
    assert orders_kpi.trend == "up"

    # Conversion Rate grew from 2.0 to 2.5 (+25%)
    cr_kpi = kpi_map["Conversion Rate"]
    assert cr_kpi.current_value == 2.5
    assert cr_kpi.change_pct == pytest.approx(25.0)
    assert cr_kpi.trend == "up"


def test_extract_attention_and_actions(current_summary: PerformanceSummary) -> None:
    runner = CommercialDigestRunner()
    alerts = [
        InventoryAlert(
            listing_id="list_shoe_001",
            title="Carbon Shoes Size 42",
            current_stock=2,
            safety_stock=15,
            days_of_supply=1.2,
            severity=InventoryAlertSeverity.CRITICAL,
        ),
    ]

    items, actions = runner._extract_attention_and_actions(current_summary, alerts)

    assert len(items) == 1
    item = items[0]
    assert item.severity == AttentionSeverity.CRITICAL
    assert item.category == AttentionCategory.INVENTORY
    assert "Carbon Shoes Size 42" in item.title
    assert item.related_listing_id == "list_shoe_001"

    assert len(actions) == 1
    act = actions[0]
    assert act.action_type == "stage_restock"
    assert act.target_id == "list_shoe_001"
    assert act.suggested_payload["quantity"] >= 20


@pytest.mark.asyncio
async def test_headless_diagnostic_runner_execution() -> None:
    backend = InMemoryMerchantBackend()
    runner = CommercialDigestRunner(store_name="Flagship Emporium")

    digest = await runner.run_diagnostic(backend, time_range="last_7d")

    assert isinstance(digest, CommercialDigestCard)
    assert digest.digest_id.startswith("dig_")
    assert digest.store_name == "Flagship Emporium"
    assert len(digest.kpis) == 4
    assert digest.headline.startswith("Today's Overview")
    assert "gross merchandise volume" in digest.summary_narrative.lower()

    # Verify UI card payload serialization
    card_dict = digest.to_card_payload()
    assert card_dict["card_type"] == "commercial_digest"
    assert card_dict["store_name"] == "Flagship Emporium"
    assert len(card_dict["kpis"]) == 4

    # Verify Markdown rendering
    md = digest.render_markdown()
    assert "Flagship Emporium Commercial Digest" in md
    assert "Gross Merchandise Volume" in md
    assert "Needs Attention Today" in md

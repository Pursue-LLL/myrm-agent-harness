"""Unit tests for headless scheduled commerce morning digest.

[INPUT]
- myrm_agent_harness.backends.commerce::InMemoryMerchantBackend, Listing, ListingStatus
- myrm_agent_harness.backends.commerce.headless_digest::*

[OUTPUT]
- test_headless_digest_normal_smooth_run: Tests normal KPI calculation when metrics are healthy
- test_headless_digest_critical_stockout_detection: Tests critical inventory alerts and recommended actions
- test_format_digest_card_payload: Validates serialization structure for WebUI card rendering

[POS]
Ensures proactive operational insights without human prompt bottleneck.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.commerce import (
    InMemoryMerchantBackend,
    InventoryAlert,
    InventoryAlertSeverity,
    Listing,
    ListingStatus,
    PerformanceSummary,
    TopProductMetric,
)
from myrm_agent_harness.backends.commerce.headless_digest import (
    CommerceMorningDigest,
    DigestSeverity,
    HeadlessDigestRunner,
    format_digest_card_payload,
)


@pytest.fixture
def mock_merchant_backend() -> InMemoryMerchantBackend:
    backend = InMemoryMerchantBackend()
    # Inject healthy summary
    backend._summary = PerformanceSummary(
        time_range="last_7d",
        gmv=125000.0,
        order_count=1850,
        conversion_rate=0.038,
        average_order_value=67.56,
        top_products=(
            TopProductMetric(product_id="shoe_01", title="Carbon Shoe", units_sold=320, revenue=38400.0),
        ),
        critical_alert_count=0,
    )
    backend._inventory_alerts.clear()
    return backend


@pytest.mark.asyncio
async def test_headless_digest_normal_smooth_run(mock_merchant_backend: InMemoryMerchantBackend) -> None:
    runner = HeadlessDigestRunner(mock_merchant_backend, store_name="Global Retail Flagship")
    digest = await runner.run_morning_audit()

    assert digest.store_name == "Global Retail Flagship"
    assert digest.gmv == 125000.0
    assert digest.order_count == 1850
    assert digest.conversion_rate == 0.038
    assert digest.critical_alerts_count == 0
    assert "平稳" in digest.executive_summary


@pytest.mark.asyncio
async def test_headless_digest_critical_stockout_detection(mock_merchant_backend: InMemoryMerchantBackend) -> None:
    mock_merchant_backend._inventory_alerts.append(
        InventoryAlert(
            listing_id="list_low_01",
            title="Ultralight Tent",
            current_stock=2,
            safety_stock=20,
            days_of_supply=1.5,
            severity=InventoryAlertSeverity.CRITICAL,
        )
    )
    runner = HeadlessDigestRunner(mock_merchant_backend, store_name="Outdoor Gear Pro")
    digest = await runner.run_morning_audit()

    assert digest.critical_alerts_count == 1
    assert len(digest.attention_items) >= 1
    critical_item = next(it for it in digest.attention_items if it.severity == DigestSeverity.CRITICAL)
    assert critical_item.metric_name == "inventory_stock"
    assert "紧急补货" in critical_item.recommended_action
    assert critical_item.payload["listing_id"] == "list_low_01"


def test_format_digest_card_payload() -> None:
    digest = CommerceMorningDigest(
        digest_id="dig_test_123",
        store_name="Demo Store",
        generated_at=pytest.importorskip("datetime").datetime.now(pytest.importorskip("datetime").timezone.utc),
        gmv=50000.0,
        order_count=800,
        conversion_rate=0.025,
        average_order_value=62.5,
        currency="USD",
        attention_items=(),
        critical_alerts_count=0,
        executive_summary="Everything is functioning normally.",
    )

    card = format_digest_card_payload(digest)
    assert card["component"] == "commercial_morning_digest"
    assert card["digest_id"] == "dig_test_123"
    assert card["kpis"]["gmv"] == 50000.0
    assert card["critical_count"] == 0

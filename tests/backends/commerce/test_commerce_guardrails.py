"""Unit tests for Merchant Price, Promotion, and Inventory Guardrails.

[INPUT]
- myrm_agent_harness.backends.commerce::*

[OUTPUT]
- TestMerchantGuardrails: 促销深度、价格波动、补货上限、受保护字段与合规备选方案生成测试
- TestTwoPhaseEnforcement: 暂存（Stage）与应用（Apply）双阶段风控防御测试

[POS]
Tests verifying Anthropic Claude Commerce Agents `merchant-agent/core/merchant_agent/changes.py` & `gates.py` parity.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.commerce import (
    ChangeType,
    Listing,
    ListingStatus,
    MerchantGuardrailConfig,
    PricingContext,
    check_merchant_guardrails,
)


@pytest.fixture
def sample_listing() -> Listing:
    return Listing(
        listing_id="list_camera_01",
        title="Mirrorless Digital Camera 4K",
        description="Professional compact camera with interchangeable lenses.",
        price=1000.0,
        inventory_count=50,
        status=ListingStatus.ACTIVE,
        category="electronics",
        tags=("camera", "photo", "4k"),
    )


@pytest.fixture
def sample_pricing_context() -> PricingContext:
    return PricingContext(
        listing_id="list_camera_01",
        current_price=1000.0,
        cost=500.0,
        margin_pct=50.0,
        min_allowed_price=750.0,
        max_allowed_price=1500.0,
        competitors=(),
    )


class TestMerchantGuardrails:
    """Test suite for business boundary guardrails."""

    def test_protected_fields_immutability(self, sample_listing: Listing) -> None:
        # Attempt to tamper with protected listing_id or category
        res = check_merchant_guardrails(
            listing=sample_listing,
            change_type=ChangeType.CONTENT_UPDATE,
            proposed_values={"listing_id": "tampered_id", "title": "New Title"},
        )
        assert res.decision == "blocked"
        assert not res.allowed
        assert any(v.field == "listing_id" for v in res.violations)
        assert "strictly read-only" in res.guidance_prompt

    def test_price_drop_within_limits_allowed(
        self, sample_listing: Listing, sample_pricing_context: PricingContext
    ) -> None:
        # 1000 -> 800 is a 20% drop (max is 25%) -> allowed
        res = check_merchant_guardrails(
            listing=sample_listing,
            change_type=ChangeType.PRICE_UPDATE,
            proposed_values={"price": 800.0},
            pricing_context=sample_pricing_context,
        )
        assert res.decision == "passed"
        assert res.allowed
        assert not res.violations

    def test_price_drop_excessive_blocked_with_compliant_alternative(
        self, sample_listing: Listing, sample_pricing_context: PricingContext
    ) -> None:
        # 1000 -> 500 is a 50% drop (max is 25%) -> blocked
        config = MerchantGuardrailConfig(max_price_drop_pct=25.0)
        res = check_merchant_guardrails(
            listing=sample_listing,
            change_type=ChangeType.PRICE_UPDATE,
            proposed_values={"price": 500.0},
            config=config,
            pricing_context=sample_pricing_context,
        )
        assert res.decision == "blocked"
        assert not res.allowed
        v = next(item for item in res.violations if item.field == "price")
        assert "exceeds maximum allowed price reduction limit" in v.message
        assert v.compliant_alternative is not None
        assert "750.00" in v.compliant_alternative  # 1000 * (1 - 0.25)
        assert "Agent Guidance" in res.guidance_prompt

    def test_promotion_discount_depth_guardrail(self, sample_listing: Listing) -> None:
        # 50% discount exceeds max 30% discount cap
        config = MerchantGuardrailConfig(max_promotion_discount_pct=30.0)
        res = check_merchant_guardrails(
            listing=sample_listing,
            change_type=ChangeType.PROMOTION,
            proposed_values={"discount_pct": 50.0},
            config=config,
        )
        assert res.decision == "blocked"
        assert not res.allowed
        v = next(item for item in res.violations if item.field == "discount_pct")
        assert "exceeds maximum allowed limit of 30.0%" in v.message
        assert v.compliant_alternative is not None
        assert "at most 30.0%" in v.compliant_alternative

    def test_campaign_budget_cap(self, sample_listing: Listing) -> None:
        config = MerchantGuardrailConfig(max_campaign_budget=5000.0)
        res = check_merchant_guardrails(
            listing=sample_listing,
            change_type=ChangeType.PROMOTION,
            proposed_values={"campaign_budget": 8000.0, "discount_pct": 15.0},
            config=config,
        )
        assert res.decision == "blocked"
        assert not res.allowed
        v = next(item for item in res.violations if item.field == "campaign_budget")
        assert "exceeds cap of 5000.00" in v.message
        assert "5000.00" in v.compliant_alternative

    def test_restock_units_cap(self, sample_listing: Listing) -> None:
        config = MerchantGuardrailConfig(max_restock_units=500)
        res = check_merchant_guardrails(
            listing=sample_listing,
            change_type=ChangeType.RESTOCK,
            proposed_values={"units": 1500},
            config=config,
        )
        assert res.decision == "blocked"
        assert not res.allowed
        v = next(item for item in res.violations if item.field == "units")
        assert "exceeds safety ceiling of 500 units" in v.message
        assert "at most 500 units" in v.compliant_alternative

    def test_two_phase_enforcement_apply_phase(
        self, sample_listing: Listing, sample_pricing_context: PricingContext
    ) -> None:
        res = check_merchant_guardrails(
            listing=sample_listing,
            change_type=ChangeType.PRICE_UPDATE,
            proposed_values={"price": 100.0},
            pricing_context=sample_pricing_context,
            is_apply_phase=True,
        )
        assert res.decision == "blocked"
        assert "[Apply Guardrail Blocked]" in res.guidance_prompt

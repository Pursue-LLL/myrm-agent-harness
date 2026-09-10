"""Tests for Commerce Session Slices & Automated Eval Generation.

[INPUT]
- myrm_agent_harness.backends.commerce.slices::*
- myrm_agent_harness.backends.commerce.types::CommerceRole

[OUTPUT]
- Unit tests verifying slice export, assertion evaluation, and regression outcomes.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.commerce.slices import (
    CommerceSessionSlice,
    CommerceSliceEvalCase,
    SliceAssertion,
    SliceStep,
    export_commerce_slice_eval,
    run_commerce_slice_regression,
)
from myrm_agent_harness.backends.commerce.types import CommerceRole


def test_export_commerce_slice_eval() -> None:
    """Verifies that a conversational session slice transforms cleanly into an eval case."""
    steps = [
        SliceStep(step_index=1, actor="user", content="我想订购两双零售慢跑鞋 42码"),
        SliceStep(
            step_index=2,
            actor="assistant",
            content="已为您添加 42 码慢跑鞋到购物车",
            action_type="add_to_cart",
            action_payload={"product_id": "prod_shoes_01", "quantity": 2},
        ),
    ]

    slice_obj = CommerceSessionSlice(
        slice_id="slice_20260910_001",
        session_id="sess_retail_998",
        domain="retail",
        role=CommerceRole.STOREFRONT,
        created_at_iso="2026-09-10T03:00:00Z",
        steps=steps,
        state_snapshot={
            "cart_items_count": 2,
            "cart_total_usd": 159.98,
            "variant_selected": "size_42",
        },
        metadata={"channel": "web_chat"},
    )

    assertions = [
        SliceAssertion(
            target_path="cart_items_count",
            assertion_type="equals",
            expected_value=2,
            description="Cart must contain exactly 2 items",
        ),
        SliceAssertion(
            target_path="cart_total_usd",
            assertion_type="less_than_or_equal",
            expected_value=200.0,
            description="Cart total must not exceed limit",
        ),
    ]

    eval_dict = export_commerce_slice_eval(
        session_slice=slice_obj,
        title="Retail Shopper Running Shoes Checkout Eval",
        assertions=assertions,
        tags=["retail", "shoes", "cart_eval"],
    )

    assert eval_dict["case_id"] == "eval_slice_20260910_001"
    assert eval_dict["title"] == "Retail Shopper Running Shoes Checkout Eval"
    assert eval_dict["domain"] == "retail"
    assert eval_dict["role"] == CommerceRole.STOREFRONT.value
    assert eval_dict["user_query"] == "我想订购两双零售慢跑鞋 42码"
    assert len(eval_dict["assertions"]) == 2
    assert "shoes" in eval_dict["tags"]


def test_run_commerce_slice_regression_all_passed() -> None:
    """Verifies successful regression evaluation when runtime matches all assertions."""
    eval_case = CommerceSliceEvalCase(
        case_id="eval_merchant_pricing_01",
        title="Merchant Price Drop Guardrail Regression",
        domain="retail",
        role=CommerceRole.MERCHANT,
        user_query="下调清仓衬衫价格 10%",
        context_slice_id="slice_merchant_01",
        assertions=[
            SliceAssertion(
                target_path="guardrail_verdict",
                assertion_type="guardrail_passed",
                description="Moderate price drop must pass guardrail",
            ),
            SliceAssertion(
                target_path="price_drop_pct",
                assertion_type="less_than_or_equal",
                expected_value=20.0,
                description="Drop percentage within safe bounds",
            ),
            SliceAssertion(
                target_path="approval_status",
                assertion_type="contains",
                expected_value="pending",
                description="Status must be pending approval",
            ),
        ],
    )

    runtime_state = {
        "guardrail_verdict": True,
        "price_drop_pct": 10.0,
        "approval_status": "pending_merchant_review",
    }

    result = run_commerce_slice_regression(eval_case, runtime_state)

    assert result.passed is True
    assert result.total_assertions == 3
    assert result.passed_assertions == 3
    assert len(result.failed_assertions) == 0


def test_run_commerce_slice_regression_with_failures() -> None:
    """Verifies detailed failure reporting when assertions are violated."""
    eval_case = CommerceSliceEvalCase(
        case_id="eval_telecom_roaming_01",
        title="Telecom Roaming Package Gate Check",
        domain="telecom",
        role=CommerceRole.STOREFRONT,
        user_query="开通欧洲漫游包",
        context_slice_id="slice_telecom_01",
        assertions=[
            SliceAssertion(
                target_path="roaming_active",
                assertion_type="equals",
                expected_value=True,
                description="Roaming must be active",
            ),
            SliceAssertion(
                target_path="roaming_cost",
                assertion_type="less_than_or_equal",
                expected_value=30.0,
                description="Roaming cost ceiling",
            ),
        ],
    )

    runtime_state = {
        "roaming_active": False,  # Failure
        "roaming_cost": 50.0,  # Failure (> 30.0)
    }

    result = run_commerce_slice_regression(eval_case, runtime_state)

    assert result.passed is False
    assert result.total_assertions == 2
    assert result.passed_assertions == 0
    assert len(result.failed_assertions) == 2
    assert "roaming_active" in result.failed_assertions[0]
    assert "roaming_cost" in result.failed_assertions[1]

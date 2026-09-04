"""Unit tests for Spend Governance, YOLO-proof Financial Gate, and Digest Binding."""

import pytest
from langchain_core.messages import AIMessage, ToolCall

from myrm_agent_harness.agent.middlewares.approval._batch_decisions import (
    apply_approval_decisions,
    build_interrupt_payload,
)
from myrm_agent_harness.agent.middlewares.approval.batch_processor import (
    evaluate_tool_batch,
)
from myrm_agent_harness.agent.security.types import SecurityConfig
from myrm_agent_harness.core.security.spend_governance import (
    DEFAULT_SPEND_SALT,
    GENESIS_PREV_HASH,
    SpendPolicy,
    SpendReceipt,
    compute_action_digest,
    compute_entry_hash,
    is_financial_or_spend_tool,
    parse_spend_amount,
    verify_action_digest,
)


def test_is_financial_or_spend_tool():
    assert is_financial_or_spend_tool("mcp__stripe__charge_customer") is True
    assert is_financial_or_spend_tool("payment_gateway") is True
    assert is_financial_or_spend_tool("checkout_order") is True
    assert is_financial_or_spend_tool("transfer_funds") is True
    assert is_financial_or_spend_tool("custom_tool", {"amount": 50}) is True
    assert is_financial_or_spend_tool("fetch_weather", {"city": "Paris"}) is False


def test_parse_spend_amount():
    amt, cur = parse_spend_amount({"amount": 25.5, "currency": "EUR"})
    assert amt == 25.5
    assert cur == "EUR"

    # Default currency is USD
    amt2, cur2 = parse_spend_amount({"price": 100})
    assert amt2 == 100.0
    assert cur2 == "USD"

    # Cent conversion if flagged
    amt3, cur3 = parse_spend_amount({"price_cents": 5000, "currency": "USD"})
    assert amt3 == 50.0
    assert cur3 == "USD"

    # None if missing
    amt4, cur4 = parse_spend_amount({"target": "none"})
    assert amt4 is None
    assert cur4 is None


def test_action_digest_and_verification():
    tool = "stripe_charge"
    args = {"amount": 35.0, "currency": "USD", "account": "acc_test"}
    digest = compute_action_digest(tool, args)
    assert len(digest) == 64

    # Valid check
    assert verify_action_digest(tool, args, digest) is True

    # Tampered args must fail
    tampered_args = {"amount": 350.0, "currency": "USD", "account": "acc_test"}
    assert verify_action_digest(tool, tampered_args, digest) is False

    # Empty digest must fail
    assert verify_action_digest(tool, args, "") is False


def test_spend_policy_caps():
    policy = SpendPolicy(per_action_cap=50.0, session_cap=100.0, enabled=True)

    # Within cap
    ok, _ = policy.is_action_allowed(30.0, current_session_spent=0.0)
    assert ok is True

    # Exceeds per-action cap
    ok, reason = policy.is_action_allowed(60.0, current_session_spent=0.0)
    assert ok is False
    assert "exceeds per-action cap" in reason

    # Exceeds session cap
    ok, reason = policy.is_action_allowed(40.0, current_session_spent=70.0)
    assert ok is False
    assert "exceeds session cap" in reason


def test_tamper_evident_receipt_integrity():
    prev = GENESIS_PREV_HASH
    ts = 1700000000.0
    tool = "mcp_stripe_charge"
    amount = 25.0
    currency = "USD"
    digest = "aabbcc" * 10
    idempotency = "idem_123"

    entry_hash = compute_entry_hash(
        prev_hash=prev,
        timestamp=ts,
        tool_name=tool,
        amount=amount,
        currency=currency,
        action_digest=digest,
        idempotency_key=idempotency,
    )

    receipt = SpendReceipt(
        entry_id="rec_1",
        session_id="sess_1",
        prev_hash=prev,
        entry_hash=entry_hash,
        tool_name=tool,
        amount=amount,
        currency=currency,
        action_digest=digest,
        idempotency_key=idempotency,
        timestamp=ts,
    )

    assert receipt.verify_integrity() is True

    # Tampered receipt amount
    bad_receipt = SpendReceipt(
        entry_id="rec_1",
        session_id="sess_1",
        prev_hash=prev,
        entry_hash=entry_hash,
        tool_name=tool,
        amount=999.0,  # tampered!
        currency=currency,
        action_digest=digest,
        idempotency_key=idempotency,
        timestamp=ts,
    )
    assert bad_receipt.verify_integrity() is False


@pytest.mark.asyncio
async def test_yolo_financial_gate_blocks_auto_approval():
    config = SecurityConfig(yolo_mode_enabled=True)
    tool_calls: list[ToolCall] = [
        {"name": "mcp__stripe__charge_customer", "args": {"amount": 15.0, "currency": "USD"}, "id": "call_1"},
    ]

    auto_approved, auto_denied, pending = await evaluate_tool_batch(
        tool_calls=tool_calls,
        config=config,
        is_cron=False,
        workspace_root=None,
        session_key="test_session",
        args_hashes={0: "hash_0"},
    )

    # Must NOT be auto-approved despite YOLO mode!
    assert len(auto_approved) == 0
    assert len(pending) == 1
    idx, tc, perm_type, reason, extra_ctx = pending[0]
    assert idx == 0
    assert extra_ctx["is_spend"] is True
    assert extra_ctx["spend_amount"] == 15.0
    assert "action_digest" in extra_ctx


@pytest.mark.asyncio
async def test_apply_approval_decisions_digest_binding_protection():
    tool_name = "mcp__stripe__charge_customer"
    args = {"amount": 20.0, "currency": "USD"}
    call_id = "tc_stripe_1"
    tool_call: ToolCall = {"name": tool_name, "args": args, "id": call_id}
    last_ai_msg = AIMessage(content="", tool_calls=[tool_call])

    expected_digest = compute_action_digest(tool_name, args)
    extra_ctx = {
        "is_spend": True,
        "spend_amount": 20.0,
        "spend_currency": "USD",
        "action_digest": expected_digest,
    }
    pending = [(0, tool_call, "spend", "Financial spend", extra_ctx)]

    # Case 1: Tampered or mismatched digest in decision
    bad_decision = [{"type": "approve", "action_digest": "tampered_digest_value_123"}]
    revised, messages, _ = await apply_approval_decisions(
        decisions=bad_decision,
        last_ai_msg=last_ai_msg,
        auto_denied=[],
        pending_approval=pending,
        interrupt_indices=[0],
        args_hashes={0: "hash_0"},
    )
    # Must be blocked and return error ToolMessage
    assert len(revised) == 0
    assert len(messages) == 1
    assert "Financial action digest verification failed" in messages[0].content

    # Case 2: Matching digest in decision -> Allowed and idempotency_key injected
    good_decision = [{"type": "approve", "action_digest": expected_digest}]
    revised_ok, messages_ok, _ = await apply_approval_decisions(
        decisions=good_decision,
        last_ai_msg=last_ai_msg,
        auto_denied=[],
        pending_approval=pending,
        interrupt_indices=[0],
        args_hashes={0: "hash_0"},
    )
    assert len(revised_ok) == 1
    assert revised_ok[0]["name"] == tool_name
    assert "idempotency_key" in revised_ok[0]["args"]

"""Tests for Agent Commerce spend governance, action digest, and receipts."""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.spend_governance import (
    DEFAULT_SPEND_SALT,
    SpendPolicy,
    SpendReceipt,
    compute_action_digest,
    compute_entry_hash,
    is_financial_or_spend_tool,
    parse_spend_amount,
    verify_action_digest,
)


def test_is_financial_or_spend_tool_by_name() -> None:
    assert is_financial_or_spend_tool("stripe_charge") is True
    assert is_financial_or_spend_tool("paypal_transfer") is True
    assert is_financial_or_spend_tool("checkout_order") is True
    assert is_financial_or_spend_tool("read_file") is False
    assert is_financial_or_spend_tool("bash_code_execute_tool") is False


def test_is_financial_or_spend_tool_by_args() -> None:
    assert is_financial_or_spend_tool("custom_order_tool", {"amount": 100}) is True
    assert is_financial_or_spend_tool("vendor_api", {"charge_amount": 25.5}) is True
    assert is_financial_or_spend_tool("search_products", {"query": "shoes"}) is False


def test_parse_spend_amount_and_currency() -> None:
    amt, cur = parse_spend_amount({"amount": "49.99", "currency": "eur"})
    assert amt == 49.99
    assert cur == "EUR"

    # Stripe cents normalized to dollars
    amt_cents, cur_usd = parse_spend_amount({"price_cents": 5000, "currency": "USD"})
    assert amt_cents == 50.0
    assert cur_usd == "USD"

    # Missing amount
    amt_none, cur_none = parse_spend_amount({"query": "balance"})
    assert amt_none is None
    assert cur_none is None


def test_compute_and_verify_action_digest() -> None:
    tool_name = "stripe_charge"
    args = {"amount": 50, "currency": "USD", "customer_id": "cus_123"}

    digest = compute_action_digest(tool_name, args)
    assert isinstance(digest, str)
    assert len(digest) == 64

    # Verify identical arguments
    assert verify_action_digest(tool_name, args, digest) is True

    # Canonical sorting: reordered keys still produce matching signature
    reordered_args = {"customer_id": "cus_123", "currency": "USD", "amount": 50}
    assert verify_action_digest(tool_name, reordered_args, digest) is True

    # Tampered amount must fail
    tampered_args = {"customer_id": "cus_123", "currency": "USD", "amount": 500}
    assert verify_action_digest(tool_name, tampered_args, digest) is False

    # Tampered tool name must fail
    assert verify_action_digest("other_tool", args, digest) is False


def test_spend_policy_caps() -> None:
    policy = SpendPolicy(per_action_cap=100.0, session_cap=250.0, enabled=True, currency="USD")

    # Allowed within cap
    ok, _ = policy.is_action_allowed(50.0, current_session_spent=0.0)
    assert ok is True

    # Exceeds per-action cap
    ok_action_cap, reason = policy.is_action_allowed(120.0, current_session_spent=0.0)
    assert ok_action_cap is False
    assert "exceeds per-action cap" in reason

    # Exceeds session cap
    ok_session_cap, reason2 = policy.is_action_allowed(80.0, current_session_spent=200.0)
    assert ok_session_cap is False
    assert "exceeds session cap" in reason2


def test_spend_receipt_cryptographic_chain() -> None:
    prev_hash = "0" * 64
    ts = time.time()
    tool_name = "checkout_pay"
    digest = compute_action_digest(tool_name, {"amount": 20})
    idempotency_key = "idemp_abc_123"

    entry_hash = compute_entry_hash(
        prev_hash=prev_hash,
        timestamp=ts,
        tool_name=tool_name,
        amount=20.0,
        currency="USD",
        action_digest=digest,
        idempotency_key=idempotency_key,
        secret_salt=DEFAULT_SPEND_SALT,
    )

    receipt = SpendReceipt(
        entry_id="rec_001",
        session_id="sess_abc",
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        tool_name=tool_name,
        amount=20.0,
        currency="USD",
        action_digest=digest,
        idempotency_key=idempotency_key,
        timestamp=ts,
    )

    # Valid receipt
    assert receipt.verify_integrity() is True

    # Tampered receipt amount
    tampered_receipt = SpendReceipt(
        entry_id="rec_001",
        session_id="sess_abc",
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        tool_name=tool_name,
        amount=2000.0,  # Tampered!
        currency="USD",
        action_digest=digest,
        idempotency_key=idempotency_key,
        timestamp=ts,
    )
    assert tampered_receipt.verify_integrity() is False


def test_is_irreversible_social_action() -> None:
    from myrm_agent_harness.core.security.spend_governance import (
        is_irreversible_social_action,
    )

    assert is_irreversible_social_action("channel_notify", {"message": "hello"}) is True
    assert is_irreversible_social_action("channel_notify_tool", {"channel": "ops"}) is True
    assert is_irreversible_social_action("artifact_publish", {"pkg": "foo"}) is True
    assert is_irreversible_social_action("shell_exec", {"command": "git push origin main"}) is True
    assert is_irreversible_social_action("shell_exec", {"command": "git push --force origin main"}) is True
    assert is_irreversible_social_action("shell_exec", {"command": "git -C /workspace push origin main"}) is True
    assert is_irreversible_social_action("bash", {"command": "git --no-pager push"}) is True
    assert is_irreversible_social_action("bash", {"command": "git status && git -C repo push"}) is True
    assert is_irreversible_social_action("bash", {"command": "git push && echo done"}) is True
    assert is_irreversible_social_action("bash", {"command": "git checkout -b feature && git commit -m 'wip'"}) is False
    assert is_irreversible_social_action("bash", {"command": "npm publish"}) is True
    assert is_irreversible_social_action("bash", {"command": "pnpm --filter pkg publish"}) is True
    assert is_irreversible_social_action("terminal", {"cmd": "twine upload dist/*"}) is True
    assert is_irreversible_social_action("shell_exec", {"command": "git status"}) is False
    assert is_irreversible_social_action("shell_exec", {"command": "git commit -m 'fix'"}) is False
    assert is_irreversible_social_action("read_file", {"path": "a.txt"}) is False


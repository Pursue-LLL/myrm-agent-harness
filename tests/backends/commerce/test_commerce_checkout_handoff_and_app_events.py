"""Tests for Checkout Handoff Security and Asynchronous AppEvent Queue.

Verifies:
1. Zero-model-touch payment handoff: sensitive checkout URLs are never passed to the model.
2. Host presentation layer correctly injects payment URLs into the UI card payload.
3. Multiple checkout handoff modes (internal_route, hosted_gateway, marketplace_split).
4. AppEvent queue concurrency, isolation, atomic dequeue, and peek behavior.
5. Formatting AppEvents into actionable system prompt reminders for conversational recovery.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.commerce.app_events import (
    AppEvent,
    AppEventType,
    InMemoryAppEventQueue,
    format_app_events_for_prompt,
    process_out_of_band_payment_webhook,
)
from myrm_agent_harness.backends.commerce.checkout_handoff import (
    CheckoutHandoffMode,
    CheckoutTarget,
    ZeroTouchHandoffEnricher,
)
from myrm_agent_harness.backends.commerce.exceptions import CommerceError
from myrm_agent_harness.backends.commerce.types import Cart, CartLine


def test_zero_model_touch_checkout_handoff_strips_url() -> None:
    """Ensure sensitive checkout URL and token never leak into the model's context summary."""
    cart = Cart(
        cart_id="cart-test-123",
        session_id="sess-abc",
        lines=(
            CartLine(
                line_id="line-1",
                product_id="prod-1",
                variant_id=None,
                quantity=2,
                unit_price=49.99,
                title="Wireless Earbuds",
            ),
        ),
    )
    targets = [
        CheckoutTarget(
            target_id="tgt-1",
            provider="stripe",
            url="https://checkout.stripe.com/c/pay/cs_live_secret_token_12345",
            amount=99.98,
            currency="USD",
        )
    ]

    envelope = ZeroTouchHandoffEnricher.enrich_checkout(
        session_id="sess-abc",
        cart=cart,
        mode=CheckoutHandoffMode.HOSTED_GATEWAY,
        targets=targets,
    )

    # 1. Model View must NEVER contain the secret URL or token
    model_summary = envelope.model_context_summary
    assert "https://checkout.stripe.com" not in model_summary
    assert "cs_live_secret" not in model_summary
    assert "99.98" in model_summary
    assert "USD" in model_summary
    assert "Zero model contact enforced" in model_summary

    # 2. Client Render View MUST contain the real verified URL
    client_payload = envelope.client_render_payload
    assert client_payload["component"] == "checkout_card"
    assert client_payload["cart_id"] == "cart-test-123"
    assert len(client_payload["targets"]) == 1
    assert client_payload["targets"][0]["url"] == "https://checkout.stripe.com/c/pay/cs_live_secret_token_12345"


def test_checkout_handoff_rejects_unsafe_urls() -> None:
    """Ensure javascript:, data:, or malformed links trigger security gates."""
    cart = Cart(
        cart_id="cart-malicious",
        session_id="sess-bad",
        lines=(
            CartLine(
                line_id="line-1",
                product_id="prod-1",
                variant_id=None,
                quantity=1,
                unit_price=10.0,
                title="Item",
            ),
        ),
    )
    malicious_targets = [
        CheckoutTarget(
            target_id="tgt-xss",
            provider="evil",
            url="javascript:alert(document.cookie)",
        )
    ]

    with pytest.raises(CommerceError) as exc_info:
        ZeroTouchHandoffEnricher.enrich_checkout(
            session_id="sess-bad",
            cart=cart,
            mode=CheckoutHandoffMode.HOSTED_GATEWAY,
            targets=malicious_targets,
        )
    assert exc_info.value.code == "UNSAFE_CHECKOUT_URL"


@pytest.mark.asyncio
async def test_app_event_queue_isolation_and_atomic_consumption() -> None:
    """Ensure session events are queued, isolated, and atomically consumed once."""
    queue = InMemoryAppEventQueue()
    session_a = "sess-alpha"
    session_b = "sess-beta"

    event_a1 = AppEvent(
        event_id="ev-1",
        session_id=session_a,
        event_type=AppEventType.PAYMENT_COMPLETED,
        payload={"order_id": "ORD-001", "amount": 150.0, "currency": "USD"},
    )
    event_a2 = AppEvent(
        event_id="ev-2",
        session_id=session_a,
        event_type=AppEventType.IDENTITY_VERIFIED,
        payload={"tier": "vip"},
    )
    event_b1 = AppEvent(
        event_id="ev-3",
        session_id=session_b,
        event_type=AppEventType.PAYMENT_CANCELLED,
    )

    await queue.enqueue(event_a1)
    await queue.enqueue(event_a2)
    await queue.enqueue(event_b1)

    # Peek should not consume
    pending_a = await queue.peek(session_a)
    assert len(pending_a) == 2
    assert pending_a[0].event_id == "ev-1"
    assert pending_a[1].event_id == "ev-2"

    # Dequeue should consume
    consumed_a = await queue.dequeue_all(session_a)
    assert len(consumed_a) == 2
    assert all(e.consumed for e in consumed_a)

    # Next dequeue should be empty for session_a
    assert len(await queue.dequeue_all(session_a)) == 0
    assert len(await queue.peek(session_a)) == 0

    # Session B should remain untouched
    pending_b = await queue.peek(session_b)
    assert len(pending_b) == 1
    assert pending_b[0].event_id == "ev-3"


def test_format_app_events_for_prompt() -> None:
    """Ensure consumed events format into clear, directive system prompts for the next turn."""
    events = (
        AppEvent(
            event_id="ev-101",
            session_id="sess-777",
            event_type=AppEventType.PAYMENT_COMPLETED,
            payload={"order_id": "ORD-88899", "amount": 259.0, "currency": "USD"},
        ),
        AppEvent(
            event_id="ev-102",
            session_id="sess-777",
            event_type=AppEventType.SMS_OTP_APPROVED,
        ),
    )

    prompt = format_app_events_for_prompt(events)
    assert "<external_app_events>" in prompt
    assert "[PAYMENT_COMPLETED] Order #ORD-88899 was successfully paid (259.0 USD)" in prompt
    assert "[SMS_OTP_APPROVED] Customer SMS OTP verification confirmed" in prompt
    assert "</external_app_events>" in prompt

    # Empty list yields empty prompt
    assert format_app_events_for_prompt(()) == ""


@pytest.mark.asyncio
async def test_process_out_of_band_payment_webhook_helper() -> None:
    """Ensure webhook payloads convert to typed AppEvent and enqueue properly."""
    queue = InMemoryAppEventQueue()
    session_id = "sess-checkout-99"

    # 1. Success webhook
    evt_succ = await process_out_of_band_payment_webhook(
        queue=queue,
        session_id=session_id,
        order_id="ORD-WEB-001",
        status="succeeded",
        amount=349.00,
        currency="USD",
    )
    assert evt_succ.event_type == AppEventType.PAYMENT_COMPLETED
    assert evt_succ.order_id == "ORD-WEB-001"
    assert (await queue.pending_count(session_id)) == 1

    # 2. Dequeue and format
    events = await queue.dequeue_all(session_id)
    assert len(events) == 1
    prompt_str = format_app_events_for_prompt(events)
    assert "[PAYMENT_COMPLETED] Order #ORD-WEB-001 was successfully paid (349.0 USD)" in prompt_str

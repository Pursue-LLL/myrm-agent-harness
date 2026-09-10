"""Unit tests for out-of-band checkout handoff and asynchronous app event queue.

[INPUT]
- myrm_agent_harness.backends.commerce.checkout_handoff::*

[OUTPUT]
- test_zero_model_touch_checkout_isolation: Confirms model card contains NO checkout_url
- test_inject_checkout_url_to_card: Host injection attaches real checkout_url for UI
- test_in_memory_app_event_queue_lifecycle: Enqueue, peek, dequeue, session isolation
- test_process_out_of_band_payment_webhook_completed: Webhook handling for successful payments
- test_process_out_of_band_payment_webhook_failed: Webhook handling for failed payments

[POS]
Ensures compliance with PCI-DSS isolation and seamless session wake-up.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from myrm_agent_harness.backends.commerce.app_events import (
    AppEvent,
    AppEventType,
    InMemoryAppEventQueue,
    format_app_events_for_prompt,
    process_out_of_band_payment_webhook,
)
from myrm_agent_harness.backends.commerce.checkout_handoff import (
    PAYMENT_HANDOFF_GATE,
    CheckoutHandoffMode,
    CheckoutHandoffPayload,
    CheckoutTarget,
    ZeroTouchHandoffEnricher,
    ZeroTouchHandoffEnvelope,
)
from myrm_agent_harness.backends.commerce.exceptions import CommerceError
from myrm_agent_harness.backends.commerce.types import Cart, CartLine


def test_zero_model_touch_checkout_isolation() -> None:
    cart = Cart(
        cart_id="cart_abc_123",
        session_id="sess_shopper_abc",
        lines=(
            CartLine(
                line_id="line_1",
                product_id="prod_1",
                variant_id=None,
                quantity=3,
                unit_price=66.66333,
            ),
        ),
        currency="USD",
    )
    targets = [
        CheckoutTarget(
            target_id="tgt_stripe_1",
            provider="stripe",
            url="https://pay.stripe.com/cs_live_secret123",
            amount=199.99,
            currency="USD",
        )
    ]

    envelope = ZeroTouchHandoffEnricher.enrich_checkout(
        session_id="sess_shopper_abc",
        cart=cart,
        mode=CheckoutHandoffMode.HOSTED_GATEWAY,
        targets=targets,
    )

    # 1. Model context must NEVER contain payment url or raw tokens
    assert "https://pay.stripe.com" not in envelope.model_context_summary
    assert "Zero model contact enforced" in envelope.model_context_summary
    assert PAYMENT_HANDOFF_GATE in envelope.model_context_summary

    # 2. Client render payload must contain executable checkout destination
    assert envelope.client_render_payload["component"] == "checkout_card"
    assert envelope.client_render_payload["cart_id"] == "cart_abc_123"
    targets_payload = envelope.client_render_payload["targets"]
    assert isinstance(targets_payload, list)
    assert len(targets_payload) == 1
    assert targets_payload[0]["url"] == "https://pay.stripe.com/cs_live_secret123"


def test_checkout_security_gate_blocks_unsafe_url() -> None:
    cart = Cart(
        cart_id="cart_safe_1",
        session_id="sess_user_1",
        lines=(CartLine(line_id="l1", product_id="p1", variant_id=None, quantity=1, unit_price=10.0),),
        currency="USD",
    )
    malicious_targets = [
        CheckoutTarget(
            target_id="tgt_bad",
            provider="phishing",
            url="javascript:stealTokens()",
        )
    ]

    with pytest.raises(CommerceError) as exc_info:
        ZeroTouchHandoffEnricher.enrich_checkout(
            session_id="sess_user_1",
            cart=cart,
            mode=CheckoutHandoffMode.HOSTED_GATEWAY,
            targets=malicious_targets,
        )
    assert exc_info.value.code == "UNSAFE_CHECKOUT_URL"


@pytest.mark.asyncio
async def test_in_memory_app_event_queue_lifecycle() -> None:
    queue = InMemoryAppEventQueue()

    sess_1 = "session_user_1"
    sess_2 = "session_user_2"

    evt1 = AppEvent(
        event_id="evt_1",
        session_id=sess_1,
        event_type=AppEventType.PAYMENT_COMPLETED,
        payload={"order_id": "ord_100", "amount": 99.0},
    )
    evt2 = AppEvent(
        event_id="evt_2",
        session_id=sess_1,
        event_type=AppEventType.VERIFICATION_APPROVED,
        payload={"order_id": "ord_100"},
    )
    evt3 = AppEvent(
        event_id="evt_3",
        session_id=sess_2,
        event_type=AppEventType.ORDER_CANCELLED,
        payload={"order_id": "ord_200"},
    )

    # Enqueue
    await queue.enqueue(evt1)
    await queue.enqueue(evt2)
    await queue.enqueue(evt3)

    assert await queue.pending_count(sess_1) == 2
    assert await queue.pending_count(sess_2) == 1

    # Peek sess_1
    peeked = await queue.peek(sess_1)
    assert len(peeked) == 2
    assert peeked[0].event_id == "evt_1"
    # Peek does not drain
    assert await queue.pending_count(sess_1) == 2

    # Dequeue sess_1
    dequeued = await queue.dequeue_all(sess_1)
    assert len(dequeued) == 2
    assert dequeued[0].order_id == "ord_100"
    assert dequeued[1].event_type == AppEventType.VERIFICATION_APPROVED

    # sess_1 is now empty, sess_2 is unaffected
    assert await queue.pending_count(sess_1) == 0
    assert await queue.pending_count(sess_2) == 1

    # Drain sess_2
    dequeued_2 = await queue.dequeue_all(sess_2)
    assert len(dequeued_2) == 1
    assert dequeued_2[0].event_id == "evt_3"
    assert await queue.pending_count(sess_2) == 0


@pytest.mark.asyncio
async def test_process_out_of_band_payment_webhook_completed() -> None:
    queue = InMemoryAppEventQueue()

    event = await process_out_of_band_payment_webhook(
        queue,
        session_id="sess_shopper_007",
        order_id="ord_9999",
        status="succeeded",
        amount=199.99,
        currency="USD",
        extra={"gateway_txn_id": "tx_stripe_abc123"},
    )

    assert event.event_type == AppEventType.PAYMENT_COMPLETED
    assert event.order_id == "ord_9999"
    assert event.payload["amount"] == 199.99
    assert event.payload["gateway_txn_id"] == "tx_stripe_abc123"

    queued = await queue.dequeue_all("sess_shopper_007")
    assert len(queued) == 1
    assert queued[0].event_id == event.event_id


@pytest.mark.asyncio
async def test_process_out_of_band_payment_webhook_failed() -> None:
    queue = InMemoryAppEventQueue()

    event = await process_out_of_band_payment_webhook(
        queue,
        session_id="sess_shopper_008",
        order_id="ord_8888",
        status="card_declined",
        amount=50.0,
    )

    assert event.event_type == AppEventType.PAYMENT_FAILED
    assert event.order_id == "ord_8888"
    assert event.payload["status"] == "card_declined"

    queued = await queue.dequeue_all("sess_shopper_008")
    assert len(queued) == 1
    assert queued[0].event_type == AppEventType.PAYMENT_FAILED

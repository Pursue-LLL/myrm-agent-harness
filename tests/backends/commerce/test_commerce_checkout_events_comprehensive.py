"""Comprehensive tests for out-of-band checkout handoff and asynchronous AppEvent queue.

Verifies:
1. HandoffMode enum and CheckoutHandoff data structures.
2. Zero-Model-Touch separation: enrich_checkout_payloads produces model_view without payment_url
   and client_view with payment_url.
3. AppEventQueue lifecycle: idempotent enqueue, peek, has_pending, consume, format_and_consume.
4. Session isolation and cross-session event protection.
5. Integration with Cart DTO and multi-seller handoffs.
"""

from __future__ import annotations

from myrm_agent_harness.backends.commerce.handoff import (
    AppEvent,
    AppEventQueue,
    AppEventType,
    CheckoutHandoff,
    HandoffMode,
    enrich_checkout_payloads,
)
from myrm_agent_harness.backends.commerce.types import Cart, CartLine


def _create_sample_cart(cart_id: str = "cart_demo_01") -> Cart:
    lines = (
        CartLine(
            line_id="line_01",
            product_id="prod_shoe_001",
            variant_id="var_shoe_42",
            quantity=2,
            unit_price=49.99,
            title="Running Shoe",
        ),
        CartLine(
            line_id="line_02",
            product_id="prod_sock_002",
            variant_id=None,
            quantity=3,
            unit_price=9.99,
            title="Sports Socks",
        ),
    )
    return Cart(
        cart_id=cart_id,
        session_id="session_user_42",
        lines=lines,
        currency="USD",
    )


def test_handoff_mode_and_serialization() -> None:
    handoff = CheckoutHandoff(
        handoff_id="hf_stripe_01",
        provider="stripe",
        payment_url="https://checkout.stripe.com/c/pay/cs_live_secret123",
        mode=HandoffMode.SAME_TAB_REDIRECT,
        merchant_id="merchant_nike",
        expires_at_timestamp=1770000000,
        display_label="Pay with Stripe",
    )

    # 1. Sanitized model dictionary must strictly hide raw payment_url
    model_dict = handoff.to_sanitized_model_dict()
    assert "payment_url" not in model_dict
    assert model_dict["handoff_id"] == "hf_stripe_01"
    assert model_dict["provider"] == "stripe"
    assert "PCI-DSS Protected" in model_dict["security_fence"]

    # 2. Client rendering payload must contain executable payment_url
    client_dict = handoff.to_client_payload_dict()
    assert client_dict["payment_url"] == "https://checkout.stripe.com/c/pay/cs_live_secret123"
    assert client_dict["merchant_id"] == "merchant_nike"
    assert client_dict["mode"] == "same_tab_redirect"


def test_enrich_checkout_payloads_zero_model_touch() -> None:
    cart = _create_sample_cart()
    handoff_1 = CheckoutHandoff(
        handoff_id="hf_01",
        provider="stripe",
        payment_url="https://pay.stripe.com/secret_url_1",
        mode=HandoffMode.POPUP_WINDOW,
    )
    handoff_2 = CheckoutHandoff(
        handoff_id="hf_02",
        provider="shopify",
        payment_url="https://checkout.shopify.com/secret_url_2",
        mode=HandoffMode.HOST_NATIVE_EMBED,
    )

    model_view, client_view = enrich_checkout_payloads(cart, [handoff_1, handoff_2])

    # Model view assertions
    assert model_view["cart_id"] == "cart_demo_01"
    assert model_view["line_count"] == 2
    assert model_view["status"] == "checkout_initiated"
    model_handoffs = model_view["handoffs"]
    assert isinstance(model_handoffs, list)
    for mh in model_handoffs:
        assert isinstance(mh, dict)
        assert "payment_url" not in mh
        assert "PCI-DSS Protected" in str(mh)

    # Client view assertions
    assert client_view["status"] == "ready_for_payment"
    client_handoffs = client_view["handoffs"]
    assert isinstance(client_handoffs, list)
    assert len(client_handoffs) == 2
    assert client_handoffs[0]["payment_url"] == "https://pay.stripe.com/secret_url_1"
    assert client_handoffs[1]["payment_url"] == "https://checkout.shopify.com/secret_url_2"


def test_app_event_queue_lifecycle() -> None:
    queue = AppEventQueue()
    session_id = "sess_customer_100"

    assert not queue.has_pending(session_id)
    assert queue.peek(session_id) == []

    # 1. Enqueue event
    event_1 = AppEvent(
        event_id="evt_pay_01",
        event_type=AppEventType.PAYMENT_COMPLETED,
        session_id=session_id,
        message="Payment of 129.95 USD succeeded for Order ord_999",
        payload={"order_id": "ord_999", "amount": 129.95},
    )
    assert queue.enqueue(event_1) is True
    assert queue.has_pending(session_id) is True

    # Idempotent deduplication: identical event_id rejected
    assert queue.enqueue(event_1) is False

    # 2. Peek does not consume
    peeked = queue.peek(session_id)
    assert len(peeked) == 1
    assert peeked[0].event_id == "evt_pay_01"
    assert queue.has_pending(session_id) is True

    # 3. Enqueue second event
    event_2 = AppEvent(
        event_id="evt_verif_02",
        event_type=AppEventType.VERIFICATION_APPROVED,
        session_id=session_id,
        message="Buyer identity KYC verification completed",
        payload={"tier": "vip"},
    )
    queue.enqueue(event_2)
    assert len(queue.peek(session_id)) == 2

    # 4. Format and consume into turn prefix
    prefix = queue.format_and_consume(session_id, label="Host Updates")
    assert prefix is not None
    assert "[Host Updates:" in prefix
    assert "Payment of 129.95 USD succeeded for Order ord_999" in prefix
    assert "Buyer identity KYC verification completed" in prefix

    # 5. After consume, queue is empty
    assert not queue.has_pending(session_id)
    assert queue.format_and_consume(session_id) is None


def test_app_event_queue_session_isolation() -> None:
    queue = AppEventQueue()
    sess_a = "session_A"
    sess_b = "session_B"

    evt_a = AppEvent(
        event_id="evt_a_1",
        event_type=AppEventType.CART_UPDATED_OUT_OF_BAND,
        session_id=sess_a,
        message="Cart synced from external mobile app",
    )
    evt_b = AppEvent(
        event_id="evt_b_1",
        event_type=AppEventType.PAYMENT_FAILED,
        session_id=sess_b,
        message="Card balance insufficient",
    )

    queue.enqueue(evt_a)
    queue.enqueue(evt_b)

    assert queue.has_pending(sess_a) is True
    assert queue.has_pending(sess_b) is True

    events_a = queue.consume(sess_a)
    assert len(events_a) == 1
    assert events_a[0].event_id == "evt_a_1"

    # Session B remains pending and intact
    assert queue.has_pending(sess_a) is False
    assert queue.has_pending(sess_b) is True

    events_b = queue.consume(sess_b)
    assert len(events_b) == 1
    assert events_b[0].event_id == "evt_b_1"

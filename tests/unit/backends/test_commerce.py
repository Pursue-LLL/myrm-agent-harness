"""Unit tests for Commerce domain models and session state."""

from __future__ import annotations

from myrm_agent_harness.backends.commerce.types import (
    MerchantSessionState,
    Money,
    ShoppingSessionState,
    VariantOption,
)


def test_session_state_and_domain_models() -> None:
    shopper_state = ShoppingSessionState(
        session_id="shopper_s1",
        customer_id="cust_alice",
        active_cart_id="cart_101",
    )
    assert shopper_state.customer_id == "cust_alice"
    assert shopper_state.active_cart_id == "cart_101"

    merchant_state = MerchantSessionState(
        session_id="merchant_s1",
        merchant_id="merchant_bob",
        authorized_permissions=("admin", "inventory_manager"),
    )
    assert merchant_state.merchant_id == "merchant_bob"
    assert "admin" in merchant_state.authorized_permissions

    money = Money(amount=19.99, currency="USD")
    assert money.amount == 19.99
    assert money.currency == "USD"

    opt = VariantOption(name="Size", value="XL")
    assert opt.name == "Size"
    assert opt.value == "XL"

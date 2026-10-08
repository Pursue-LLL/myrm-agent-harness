"""Unit tests for Tri-Flow Isolation and Transaction Safety Pillars."""

from __future__ import annotations

from myrm_agent_harness.core.security.tri_flow_isolation import (
    DocumentedEndpointSpec,
    EndpointValidator,
    ToolRoleContract,
    TriFlowGuard,
    ZeroPrintCredentialVault,
)


def test_tri_flow_role_boundaries_and_rejections() -> None:
    """Test strict role boundary separation across Read-Only, Buyer, and Seller."""
    guard = TriFlowGuard()
    guard.register_tool(
        ToolRoleContract(
            tool_name="get_market_price",
            allowed_roles=("read_only", "buyer", "seller"),
        )
    )
    guard.register_tool(
        ToolRoleContract(
            tool_name="create_purchase_order",
            allowed_roles=("buyer",),
            is_financial_transaction=True,
            financial_threshold=100.0,
        )
    )
    guard.register_tool(
        ToolRoleContract(
            tool_name="seller_withdraw_funds",
            allowed_roles=("seller",),
            is_financial_transaction=True,
            requires_hitl_confirmation=True,
        )
    )

    # 1. Read-Only flow calling get_market_price -> ALLOWED
    res1 = guard.validate_tool_call(
        current_role="read_only", tool_name="get_market_price"
    )
    assert res1.is_allowed is True

    # 2. Read-Only flow attempting to call create_purchase_order -> BLOCKED
    res2 = guard.validate_tool_call(
        current_role="read_only", tool_name="create_purchase_order"
    )
    assert res2.is_allowed is False
    assert "Violation: tool 'create_purchase_order' requires roles" in res2.reason

    # 3. Buyer flow calling seller_withdraw_funds -> BLOCKED
    res3 = guard.validate_tool_call(
        current_role="buyer", tool_name="seller_withdraw_funds"
    )
    assert res3.is_allowed is False

    # 4. Unregistered tool in Read-Only flow -> BLOCKED
    res4 = guard.validate_tool_call(
        current_role="read_only", tool_name="unknown_external_tool"
    )
    assert res4.is_allowed is False


def test_financial_hitl_confirmation_enforcement() -> None:
    """Test that financial transactions requiring confirmation cannot execute without HITL."""
    guard = TriFlowGuard()
    guard.register_tool(
        ToolRoleContract(
            tool_name="transfer_tokens",
            allowed_roles=("buyer",),
            is_financial_transaction=True,
            financial_threshold=50.0,
        )
    )

    # Below threshold -> ALLOWED without HITL
    res_small = guard.validate_tool_call(
        current_role="buyer",
        tool_name="transfer_tokens",
        amount=20.0,
        hitl_confirmed=False,
    )
    assert res_small.is_allowed is True

    # Above threshold without HITL -> BLOCKED, requires_hitl=True
    res_large_unconfirmed = guard.validate_tool_call(
        current_role="buyer",
        tool_name="transfer_tokens",
        amount=200.0,
        hitl_confirmed=False,
    )
    assert res_large_unconfirmed.is_allowed is False
    assert res_large_unconfirmed.requires_hitl is True

    # Above threshold with HITL -> ALLOWED
    res_large_confirmed = guard.validate_tool_call(
        current_role="buyer",
        tool_name="transfer_tokens",
        amount=200.0,
        hitl_confirmed=True,
    )
    assert res_large_confirmed.is_allowed is True


def test_zero_guesswork_endpoint_validator() -> None:
    """Test blocking of undocumented endpoints, methods, and contract calls."""
    validator = EndpointValidator(enforce_strict=True)
    validator.register_endpoint(
        DocumentedEndpointSpec(
            service="aacp_market",
            path="/api/v1/orders/{order_id}",
            allowed_methods=("GET", "POST"),
            contract_functions=("buyService", "quotePrice"),
        )
    )

    # 1. Documented path with parameter -> ALLOWED
    res1 = validator.validate_endpoint_call(
        service="aacp_market",
        path="/api/v1/orders/ord_9988",
        method="GET",
        function_name="quotePrice",
    )
    assert res1.is_allowed is True

    # 2. Undocumented path guess -> BLOCKED
    res2 = validator.validate_endpoint_call(
        service="aacp_market",
        path="/api/v1/admin/debug_refund",
        method="POST",
    )
    assert res2.is_allowed is False
    assert "Zero-Guesswork violation: endpoint path" in res2.reason

    # 3. Disallowed method (DELETE) on documented endpoint -> BLOCKED
    res3 = validator.validate_endpoint_call(
        service="aacp_market",
        path="/api/v1/orders/ord_9988",
        method="DELETE",
    )
    assert res3.is_allowed is False
    assert "HTTP method 'DELETE' not permitted" in res3.reason

    # 4. Undocumented smart contract function -> BLOCKED
    res4 = validator.validate_endpoint_call(
        service="aacp_market",
        path="/api/v1/orders/ord_9988",
        method="POST",
        function_name="drainVault",
    )
    assert res4.is_allowed is False
    assert "contract method 'drainVault' is not declared" in res4.reason


def test_zero_print_credential_vault_sanitization() -> None:
    """Test scanning and redacting private keys from STDOUT/logs/prompts."""
    vault = ZeroPrintCredentialVault()

    raw_text = (
        "Execution logs: Connecting to Ethereum node.\n"
        "Private key is 0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d\n"
        "Stripe key: sk_live_51AbcDefGhIjKlMnOpQrStUvWxYz123456789\n"
        "All systems normal."
    )

    result = vault.sanitize_text(raw_text)
    assert result.redactions_count == 2
    assert "0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d" not in result.sanitized_text
    assert "sk_live_51AbcDefGhIjKlMnOpQrStUvWxYz123456789" not in result.sanitized_text
    assert "[REDACTED_CREDENTIAL:ethereum_private_key:" in result.sanitized_text
    assert "[REDACTED_CREDENTIAL:stripe_live_key:" in result.sanitized_text

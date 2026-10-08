"""Unit tests for Enterprise Zero-Credential Proxy and Super-CLI Suite."""

from myrm_agent_harness.core.security.zero_credential_proxy import (
    AuthHeaderScheme,
    OutboundProxyRequest,
    ProxyInjectionRule,
    RedactionSanitizationGate,
    SuperCliCommandSpec,
    SuperCliWrapper,
    ZeroCredentialOutboundProxy,
)


def test_redaction_gate_sensitive_tokens_and_model_transparency() -> None:
    gate = RedactionSanitizationGate(inject_notice=True)

    # 1. Test multiple credential redaction and model transparency notice
    leaky_output = (
        "Deployment failed! Token was ghp_1234567890abcdef1234567890abcdef1234\n"
        "OpenAI Key was sk-1234567890abcdef1234567890abcdef123456\n"
        "AWS Key was AKIAIOSFODNN7EXAMPLE\n"
    )
    result = gate.sanitize(leaky_output)

    assert result.redacted_count == 3
    assert "ghp_1234567890abcdef" not in result.sanitized_text
    assert "sk-1234567890" not in result.sanitized_text
    assert "AKIAIOSFODNN7EXAMPLE" not in result.sanitized_text
    assert "[REDACTED_SECRET]" in result.sanitized_text
    assert result.transparency_notice is not None
    assert "[Notice: 3 sensitive credential(s) redacted by security layer]" in result.sanitized_text

    # 2. Test clean text: no redactions, no notice
    clean_text = "All systems operational. Build succeeded in 4.2s."
    clean_res = gate.sanitize(clean_text)
    assert clean_res.redacted_count == 0
    assert clean_res.transparency_notice is None
    assert clean_res.sanitized_text == clean_text


def test_outbound_proxy_injection_and_domain_isolation() -> None:
    proxy = ZeroCredentialOutboundProxy()

    rule = ProxyInjectionRule(
        rule_id="github-main",
        target_domain="api.github.com",
        real_token="ghp_real_secret_token_at_boundary_99999",
        scheme=AuthHeaderScheme.BEARER,
        description="GitHub Enterprise Connector",
    )
    proxy.register_rule(rule)

    # 1. Verify token redaction in list
    rules = proxy.list_rules()
    assert len(rules) == 1
    assert rules[0].real_token == "[REDACTED_IN_VAULT]"

    # 2. Permitted outbound request with connector placeholder header
    req_allowed = OutboundProxyRequest(
        url="https://api.github.com/repos/org/repo/issues",
        method="GET",
        headers={"X-Myrm-Connector-Ref": "github-main"},
    )
    resp_allowed = proxy.process_request(req_allowed)
    assert resp_allowed.status_code == 200
    assert resp_allowed.credential_injected
    assert resp_allowed.matched_rule_id == "github-main"
    assert resp_allowed.blocked_reason is None

    # 3. Blocked outbound request (destination mismatch / exfiltration attempt)
    req_blocked = OutboundProxyRequest(
        url="https://attacker.evil.com/leak",
        method="POST",
        headers={"X-Myrm-Connector-Ref": "github-main"},
    )
    resp_blocked = proxy.process_request(req_blocked)
    assert resp_blocked.status_code == 403
    assert not resp_blocked.credential_injected
    assert "not authorized" in (resp_blocked.blocked_reason or "")

    # 4. Unmatched connector ref
    req_missing = OutboundProxyRequest(
        url="https://unknown-service.com/api",
        method="GET",
        headers={"X-Myrm-Connector-Ref": "non-existent-rule"},
    )
    resp_missing = proxy.process_request(req_missing)
    assert resp_missing.status_code == 404
    assert not resp_missing.credential_injected


def test_super_cli_wrapper_execution_and_stream_redaction() -> None:
    wrapper = SuperCliWrapper()

    spec = SuperCliCommandSpec(
        target_cli="kubectl",
        args=["get", "pods"],
        injected_env={"KUBECONFIG_TOKEN": "secret_token_123"},
    )

    # Simulate execution where raw stdout leaked a Bearer token
    simulated_stdout = (
        "NAME READY STATUS RESTARTS AGE\n"
        "pod-1 1/1 Running 0 10m\n"
        "Bearer secret_token_value_long_auth_header_1234567890\n"
    )
    result = wrapper.simulate_mock_execution(
        spec=spec,
        simulated_stdout=simulated_stdout,
        simulated_stderr="Error: none",
        exit_code=0,
    )

    assert result.exit_code == 0
    assert result.redacted_count == 1
    assert "secret_token_value_long" not in result.stdout
    assert "[REDACTED_SECRET]" in result.stdout
    assert result.transparency_notice is not None
    assert "[Notice: 1 sensitive credential(s) redacted by security layer]" in result.stdout

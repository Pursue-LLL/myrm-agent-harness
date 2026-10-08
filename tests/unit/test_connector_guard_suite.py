"""Unit tests for Connector Host Allowlist and Anti-Exfiltration SSRF Guard Suite."""

from __future__ import annotations

from myrm_agent_harness.core.security.connector_guard import (
    AntiExfiltrationGuard,
    ConnectorAllowlistEntry,
    ConnectorAllowlistRegistry,
    EnterpriseOutboundMode,
    GuardDecision,
    OutboundTrafficInspection,
    SsrfAnomalySentinel,
    ThreatKind,
)


def test_connector_allowlist_registry_matching() -> None:
    registry = ConnectorAllowlistRegistry(load_defaults=True)

    # 1. Exact match
    entry = registry.match_host("api.github.com", connector_id="github")
    assert entry is not None
    assert entry.connector_id == "github"

    # 2. Rejection of unallowed subdomains
    entry_sub = registry.match_host("attacker.api.github.com", connector_id="github")
    assert entry_sub is None

    # 3. Subdomain match when allow_subdomains=True (e.g. Jira)
    jira_entry = registry.match_host("corp.api.atlassian.com", connector_id="jira")
    assert jira_entry is not None
    assert jira_entry.connector_id == "jira"

    # 4. Custom registration
    custom = ConnectorAllowlistEntry(
        connector_id="internal_crm",
        official_hosts=("crm.corp.internal",),
        allow_subdomains=False,
    )
    registry.register(custom)
    assert registry.match_host("crm.corp.internal") is not None
    assert registry.unregister("internal_crm") is True
    assert registry.match_host("crm.corp.internal") is None


def test_ssrf_sentinel_ip_and_metadata_probes() -> None:
    sentinel = SsrfAnomalySentinel(block_private_ips=True)

    # 1. Cloud metadata IP
    threat, desc = sentinel.check_url("http://169.254.169.254/latest/meta-data/")
    assert threat == ThreatKind.SSRF_METADATA
    assert "metadata" in desc.lower()

    # 2. Localhost and loopback
    threat, desc = sentinel.check_url("http://127.0.0.1:8080/internal")
    assert threat == ThreatKind.SSRF_PRIVATE_IP

    threat_lh, _ = sentinel.check_url("http://localhost/admin")
    assert threat_lh == ThreatKind.SSRF_PRIVATE_IP

    # 3. Private RFC1918 subnets
    threat_priv, _ = sentinel.check_url("http://10.0.1.25/metrics")
    assert threat_priv == ThreatKind.SSRF_PRIVATE_IP

    threat_priv2, _ = sentinel.check_url("https://192.168.1.100/status")
    assert threat_priv2 == ThreatKind.SSRF_PRIVATE_IP

    # 4. Userinfo trick
    threat_user, _ = sentinel.check_url("https://api.github.com@evil-attacker.com/steal")
    assert threat_user == ThreatKind.HOST_SPOOFING

    # 5. Legitimate public URL
    safe_threat, _ = sentinel.check_url("https://api.github.com/repos/myrm/core")
    assert safe_threat is None


def test_token_smuggling_detection() -> None:
    sentinel = SsrfAnomalySentinel()

    # Smuggled GitHub PAT in query param
    threat, desc = sentinel.check_url(
        "https://external-webhook.site/hook?token=ghp_123456789012345678901234567890123456"
    )
    assert threat == ThreatKind.TOKEN_SMUGGLING
    assert "token" in desc.lower()

    # Smuggled OpenAI key in query param
    threat2, _ = sentinel.check_url(
        "https://evil.org/log?api_key=sk-ant-api03-abcdef12345678901234567890"
    )
    assert threat2 == ThreatKind.TOKEN_SMUGGLING

    # Smuggled key in URL path
    threat3, _ = sentinel.check_url(
        "https://evil.org/collect/ghp_123456789012345678901234567890123456"
    )
    assert threat3 == ThreatKind.TOKEN_SMUGGLING


def test_anti_exfiltration_guard_authorized_injection() -> None:
    guard = AntiExfiltrationGuard()

    traffic = OutboundTrafficInspection(
        url="https://api.github.com/user",
        method="GET",
        headers={"X-Myrm-Connector-Ref": "github", "Accept": "application/json"},
        connector_id="github",
        session_id="session-42",
    )

    result = guard.inspect_traffic(traffic)
    assert result.decision == GuardDecision.INJECT_CREDENTIALS
    assert result.can_inject_credential is True
    assert result.matched_connector_id == "github"
    assert result.detected_threat is None
    assert "Accept" in result.sanitized_headers


def test_anti_exfiltration_guard_zero_cred_downgrade() -> None:
    guard = AntiExfiltrationGuard(mode=EnterpriseOutboundMode.ZERO_CRED_PERMISSIVE)

    traffic = OutboundTrafficInspection(
        url="https://docs.python.org/3/library/",
        method="GET",
        headers={
            "Authorization": "Bearer sensitive_token",
            "Cookie": "session=secret_value",
            "User-Agent": "MyrmAgent/1.0",
        },
        session_id="session-user",
    )

    result = guard.inspect_traffic(traffic)
    assert result.decision == GuardDecision.ZERO_CREDENTIAL_ALLOW
    assert result.can_inject_credential is False
    assert result.matched_connector_id is None
    # Verify sensitive headers are stripped
    assert "Authorization" not in result.sanitized_headers
    assert "authorization" not in result.sanitized_headers
    assert "Cookie" not in result.sanitized_headers
    assert result.sanitized_headers["User-Agent"] == "MyrmAgent/1.0"


def test_anti_exfiltration_guard_strict_enterprise_blocking() -> None:
    guard = AntiExfiltrationGuard(
        mode=EnterpriseOutboundMode.STRICT_BLOCK_UNREGISTERED
    )

    traffic = OutboundTrafficInspection(
        url="https://random-public-site.org/api",
        method="GET",
        headers={},
        session_id="session-strict",
    )

    result = guard.inspect_traffic(traffic)
    assert result.decision == GuardDecision.BLOCK
    assert result.detected_threat == ThreatKind.UNREGISTERED_HOST
    assert result.can_inject_credential is False


def test_circuit_breaker_trip_and_reset() -> None:
    guard = AntiExfiltrationGuard()
    session_id = "session-malicious"

    # Attempt metadata probe
    attack = OutboundTrafficInspection(
        url="http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        session_id=session_id,
    )
    res1 = guard.inspect_traffic(attack)
    assert res1.decision == GuardDecision.BLOCK
    assert res1.detected_threat == ThreatKind.SSRF_METADATA
    assert guard.is_circuit_breaker_tripped(session_id) is True

    # Subsequent safe request is blocked because breaker is tripped
    safe_traffic = OutboundTrafficInspection(
        url="https://api.github.com/user",
        connector_id="github",
        session_id=session_id,
    )
    res2 = guard.inspect_traffic(safe_traffic)
    assert res2.decision == GuardDecision.BLOCK
    assert "TRIPPED" in res2.reason

    # Reset circuit breaker
    assert guard.reset_circuit_breaker(session_id) is True
    assert guard.is_circuit_breaker_tripped(session_id) is False

    # Now safe request is authorized
    res3 = guard.inspect_traffic(safe_traffic)
    assert res3.decision == GuardDecision.INJECT_CREDENTIALS

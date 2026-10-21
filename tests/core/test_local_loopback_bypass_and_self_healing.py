"""Unit tests for local loopback proxy bypass, probe validation, and Surge/Clash self-healing suite.

Verifies:
- Loopback target recognition (127.0.0.1, localhost, ::1, 127.x.x.x, full URLs).
- NO_PROXY merge and deduplication invariants.
- Client environment sanitization (stripping proxy variables for loopback endpoints).
- Active TCP probe latency measurement and connection status classification.
- Proxy interception diagnosis when system proxy is active without loopback bypass.
- External proxy response header fingerprinting.
- Surge and Clash rule directive generation and direct client transport kwargs.
- Diagnostic remediation card synthesis.
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.core.network import (
    HealthStatus,
    LoopbackProbe,
    LoopbackProbeResult,
    ProxyEnvironmentGuard,
    ProxySoftwareKind,
    SurgeClashSelfHealer,
)


def test_is_loopback_target_detection() -> None:
    # Positive targets
    assert ProxyEnvironmentGuard.is_loopback_target("127.0.0.1")
    assert ProxyEnvironmentGuard.is_loopback_target("127.0.0.1:8317")
    assert ProxyEnvironmentGuard.is_loopback_target("127.10.0.1")
    assert ProxyEnvironmentGuard.is_loopback_target("localhost")
    assert ProxyEnvironmentGuard.is_loopback_target("localhost:11434")
    assert ProxyEnvironmentGuard.is_loopback_target("::1")
    assert ProxyEnvironmentGuard.is_loopback_target("http://127.0.0.1:8317/v1/chat")
    assert ProxyEnvironmentGuard.is_loopback_target("https://localhost:8080/health")

    # Negative targets
    assert not ProxyEnvironmentGuard.is_loopback_target("api.anthropic.com")
    assert not ProxyEnvironmentGuard.is_loopback_target("192.168.1.100")
    assert not ProxyEnvironmentGuard.is_loopback_target("8.8.8.8")
    assert not ProxyEnvironmentGuard.is_loopback_target("https://openrouter.ai/api")


def test_proxy_environment_guard_merge_no_proxy() -> None:
    # Case 1: Empty initial no_proxy
    res1 = ProxyEnvironmentGuard.merge_no_proxy(None)
    assert "127.0.0.1" in res1
    assert "localhost" in res1
    assert "::1" in res1

    # Case 2: Existing tokens preserved and not duplicated
    res2 = ProxyEnvironmentGuard.merge_no_proxy("my-internal-host.com,127.0.0.1")
    assert res2.startswith("my-internal-host.com,127.0.0.1")
    assert res2.count("127.0.0.1") == 1
    assert "localhost" in res2


def test_enforce_loopback_bypass_and_sanitize_client_env() -> None:
    dirty_env = {
        "HTTP_PROXY": "http://127.0.0.1:7890",
        "HTTPS_PROXY": "http://127.0.0.1:7890",
        "ALL_PROXY": "socks5://127.0.0.1:7890",
        "OTHER_VAR": "keep_me",
    }

    # Connecting to loopback: all proxies must be stripped
    clean_loopback_env = ProxyEnvironmentGuard.sanitize_client_env(
        "http://127.0.0.1:8317",
        base_env=dirty_env,
    )
    assert "HTTP_PROXY" not in clean_loopback_env
    assert "HTTPS_PROXY" not in clean_loopback_env
    assert "ALL_PROXY" not in clean_loopback_env
    assert clean_loopback_env["OTHER_VAR"] == "keep_me"
    assert "127.0.0.1" in clean_loopback_env["NO_PROXY"]

    # Connecting to public external: proxies remain intact
    external_env = ProxyEnvironmentGuard.sanitize_client_env(
        "https://api.openai.com",
        base_env=dirty_env,
    )
    assert external_env["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert "127.0.0.1" in external_env["NO_PROXY"]


@pytest.mark.asyncio
async def test_loopback_probe_healthy_and_interception_detection() -> None:
    # 1. Start a temporary mock loopback TCP server
    server_ready = asyncio.Event()
    bound_port: list[int] = []

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    for sock in server.sockets or []:
        bound_port.append(sock.getsockname()[1])
    server_ready.set()

    probe = LoopbackProbe(timeout_seconds=1.0)
    try:
        # Probe healthy live server
        res_healthy = await probe.probe_tcp_port("127.0.0.1", bound_port[0])
        assert res_healthy.status == HealthStatus.HEALTHY
        assert res_healthy.is_reachable is True
        assert res_healthy.latency_ms >= 0.0
        assert not res_healthy.intercepted_by_proxy

        # Probe unopened port with proxy environment active -> classified as INTERCEPTED
        proxy_conflict_env = {
            "http_proxy": "http://127.0.0.1:7890",
            "no_proxy": "some.domain.com",  # Missing 127.0.0.1!
        }
        res_conflict = await probe.probe_tcp_port(
            "127.0.0.1", 59999, env=proxy_conflict_env
        )
        assert res_conflict.status == HealthStatus.INTERCEPTED
        assert res_conflict.intercepted_by_proxy is True
        assert res_conflict.is_reachable is False

    finally:
        server.close()
        await server.wait_closed()


def test_detect_proxy_headers() -> None:
    # Headers with Surge fingerprint
    surge_headers = {"Server": "nginx", "X-Surge-Server": "Surge/5.0"}
    detected_surge = LoopbackProbe.detect_proxy_headers(surge_headers)
    assert detected_surge is not None
    assert "X-Surge-Server" in detected_surge

    # Clean headers
    clean_headers = {"Content-Type": "application/json", "Connection": "keep-alive"}
    assert LoopbackProbe.detect_proxy_headers(clean_headers) is None


def test_surge_clash_healer_rule_generation_and_client_kwargs() -> None:
    # Surge directive
    surge_rule = SurgeClashSelfHealer.generate_bypass_rule(ProxySoftwareKind.SURGE)
    assert surge_rule.rule_directive == "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve"
    assert surge_rule.target_config_section == "[Rule]"

    # Clash directive
    clash_rule = SurgeClashSelfHealer.generate_bypass_rule(ProxySoftwareKind.CLASH)
    assert clash_rule.rule_directive == "- IP-CIDR,127.0.0.0/8,DIRECT,no-resolve"
    assert clash_rule.target_config_section == "rules:"

    # Direct client kwargs (bypassing trust_env)
    direct_kwargs = SurgeClashSelfHealer.build_direct_client_kwargs()
    assert direct_kwargs == {"trust_env": False}

    # Diagnostic alert card synthesis
    mock_probe = LoopbackProbeResult(
        target_host="127.0.0.1",
        target_port=8317,
        status=HealthStatus.INTERCEPTED,
        is_reachable=False,
        intercepted_by_proxy=True,
    )
    card = SurgeClashSelfHealer.synthesize_diagnostic_card(
        mock_probe,
        software=ProxySoftwareKind.SURGE,
    )
    assert "Local Loopback Proxy Conflict Detected" in card
    assert "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve" in card
    assert "[Rule]" in card

"""Tests for browser security features — domain filtering, URL scheme validation,
and network allowlist configuration propagation.

Covers:
- DomainAllowlist matching logic (exact, wildcard, case insensitivity)
- build_init_script JS generation (constructor hardening)
- install_domain_filter integration with mock BrowserContext
- _has_explicit_scheme edge cases (scheme vs hostname:port)
- check_navigate_scheme full scheme coverage
- network_allowlist config parsing and channel_presets merge
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.security.checks import _has_explicit_scheme, check_navigate_scheme
from myrm_agent_harness.agent.security.config import parse_security_config
from myrm_agent_harness.agent.security.engine import evaluate_tool_call
from myrm_agent_harness.agent.security.types import PermissionAction, SecurityConfig
from myrm_agent_harness.toolkits.browser.domain_filter import (
    DomainAllowlist,
    build_init_script,
    install_domain_filter,
)

# ============================================================================
# TestDomainAllowlist — matching logic
# ============================================================================


class TestDomainAllowlist:
    def test_empty_allowlist_matches_nothing(self):
        al = DomainAllowlist(patterns=())
        assert not al.is_allowed("example.com",)
        assert al.is_empty

    def test_exact_match(self):
        al = DomainAllowlist(patterns=("example.com",))
        assert al.is_allowed("example.com",)
        assert not al.is_allowed("other.com")
        assert not al.is_allowed("sub.example.com")

    def test_wildcard_match(self):
        al = DomainAllowlist(patterns=("*.example.com",))
        assert al.is_allowed("example.com",)
        assert al.is_allowed("sub.example.com")
        assert al.is_allowed("deep.sub.example.com")
        assert not al.is_allowed("notexample.com")
        assert not al.is_allowed("example.com.evil.com")

    def test_case_insensitive(self):
        al = DomainAllowlist(patterns=("example.com",))
        assert al.is_allowed("EXAMPLE.COM")
        assert al.is_allowed("Example.Com")

    def test_multiple_patterns(self):
        al = DomainAllowlist(patterns=("api.example.com", "*.cdn.net"))
        assert al.is_allowed("api.example.com")
        assert al.is_allowed("cdn.net")
        assert al.is_allowed("img.cdn.net")
        assert not al.is_allowed("example.com",)

    def test_from_strings_factory(self):
        al = DomainAllowlist.from_strings(["  Example.COM  ", "*.CDN.net", "", "  "])
        assert al.patterns == ("example.com", "*.cdn.net")
        assert al.is_allowed("example.com",)
        assert al.is_allowed("img.cdn.net")

    def test_frozen_immutable(self):
        al = DomainAllowlist(patterns=("example.com",))
        with pytest.raises(Exception):
            al.patterns = "other.com"  # type: ignore[misc]

    def test_is_empty_property(self):
        assert DomainAllowlist(patterns=()).is_empty
        assert not DomainAllowlist(patterns=("x.com")).is_empty


# ============================================================================
# TestBuildInitScript — JS hardening script generation
# ============================================================================


class TestBuildInitScript:
    def test_contains_iife_wrapper(self):
        script = build_init_script()
        assert script.startswith("(function() {")
        assert script.endswith("})();")

    def test_contains_special_api_guards(self):
        script = build_init_script()
        assert "RTCPeerConnection" in script
        assert "WebTransport" in script

    def test_patches_all_constructors(self):
        script = build_init_script()
        assert "RTCPeerConnection" in script
        assert "webkitRTCPeerConnection" in script
        assert "WebTransport" in script
        assert "serviceWorker" in script
        assert "register" in script

    def test_uses_configurable_false(self):
        script = build_init_script()
        assert "configurable: false" in script
        assert "writable: false" in script

    def test_still_generates_script(self):
        script = build_init_script()
        assert "use strict" in script


# ============================================================================
# TestInstallDomainFilter — integration with mock BrowserContext
# ============================================================================


class TestInstallDomainFilter:
    @pytest.mark.asyncio
    async def test_empty_allowlist_is_noop(self):
        ctx = AsyncMock()
        await install_domain_filter(ctx, DomainAllowlist(patterns=()))
        ctx.route.assert_not_called()
        ctx.add_init_script.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_empty_installs_route_and_script(self):
        ctx = AsyncMock()
        al = DomainAllowlist(patterns=("example.com",))
        await install_domain_filter(ctx, al, enable_cdp_audit=False)
        ctx.route.assert_called_once()
        assert ctx.add_init_script.call_count == 2
        csp_script = ctx.add_init_script.call_args_list[0][0][0]
        harden_script = ctx.add_init_script.call_args_list[1][0][0]
        assert "example.com" in csp_script
        assert "RTCPeerConnection" in harden_script

    @pytest.mark.asyncio
    async def test_cdp_audit_registers_page_listener(self):
        ctx = AsyncMock()
        al = DomainAllowlist(patterns=("example.com",))
        await install_domain_filter(ctx, al, enable_cdp_audit=True)
        ctx.on.assert_called_once()
        args = ctx.on.call_args[0]
        assert args[0] == "page"
        assert callable(args[1])

    @pytest.mark.asyncio
    async def test_cdp_audit_disabled(self):
        ctx = AsyncMock()
        al = DomainAllowlist(patterns=("example.com",))
        await install_domain_filter(ctx, al, enable_cdp_audit=False)
        ctx.on.assert_not_called()


# ============================================================================
# TestHasExplicitScheme — boundary cases
# ============================================================================


class TestHasExplicitScheme:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("http://example.com", True),
            ("https://example.com/path", True),
            ("file:///etc/passwd", True),
            ("ftp://files.example.com", True),
            ("javascript:alert(1)", True),
            ("data:text/html,hi", True),
            ("blob:https://example.com/uuid", True),
            ("chrome://settings", True),
            ("about:blank", True),
            ("localhost:3000", False),
            ("192.168.1.1:8080", False),
            ("192.168.1.1", False),
            ("example.com", False),
            ("//example.com", False),
            ("", False),
        ],
    )
    def test_scheme_detection(self, url: str, expected: bool):
        assert _has_explicit_scheme(url) == expected, f"Failed for {url!r}"


# ============================================================================
# TestCheckNavigateScheme — full scheme coverage
# ============================================================================


class TestCheckNavigateScheme:
    def test_non_navigate_permission_passes(self):
        action, _reason = check_navigate_scheme("shell_exec", {"url": "file:///etc/passwd"})
        assert action is None

    def test_empty_url_passes(self):
        action, _reason = check_navigate_scheme("browser_navigate", {"url": ""})
        assert action is None

    def test_no_url_key_passes(self):
        action, _reason = check_navigate_scheme("browser_navigate", {})
        assert action is None

    def test_http_allowed(self):
        action, _reason = check_navigate_scheme("browser_navigate", {"url": "http://example.com"})
        assert action is None

    def test_https_allowed(self):
        action, _reason = check_navigate_scheme("browser_navigate", {"url": "https://example.com/path"})
        assert action is None

    def test_file_denied(self):
        action, reason = check_navigate_scheme("browser_navigate", {"url": "file:///etc/passwd"})
        assert action == PermissionAction.DENY
        assert "file" in reason

    def test_javascript_denied(self):
        action, reason = check_navigate_scheme("browser_navigate", {"url": "javascript:alert(1)"})
        assert action == PermissionAction.DENY
        assert "javascript" in reason

    def test_data_denied(self):
        action, reason = check_navigate_scheme("browser_navigate", {"url": "data:text/html,<h1>hi</h1>"})
        assert action == PermissionAction.DENY
        assert "data" in reason

    def test_blob_denied(self):
        action, reason = check_navigate_scheme("browser_navigate", {"url": "blob:https://example.com/uuid"})
        assert action == PermissionAction.DENY
        assert "blob" in reason

    def test_ftp_denied(self):
        action, reason = check_navigate_scheme("browser_navigate", {"url": "ftp://files.example.com/secret.txt"})
        assert action == PermissionAction.DENY
        assert "ftp" in reason

    def test_about_blank_denied(self):
        """about:blank is treated as non-http scheme and denied.
        Agents should use browser_navigate without URL or use other APIs."""
        action, reason = check_navigate_scheme("browser_navigate", {"url": "about:blank"})
        assert action == PermissionAction.DENY
        assert "about" in reason

    def test_bare_hostname_passes(self):
        action, _reason = check_navigate_scheme("browser_navigate", {"url": "example.com"})
        assert action is None

    def test_localhost_port_passes(self):
        action, _reason = check_navigate_scheme("browser_navigate", {"url": "localhost:3000"})
        assert action is None

    def test_ip_port_passes(self):
        action, _reason = check_navigate_scheme("browser_navigate", {"url": "192.168.1.1:8080"})
        assert action is None


# ============================================================================
# TestNetworkAllowlistConfig — parsing and propagation
# ============================================================================


class TestNetworkAllowlistConfig:
    def test_parse_security_config_with_allowlist(self):
        raw = {"networkAllowlist": ["example.com", "*.cdn.net"]}
        config = parse_security_config(raw)
        assert config is not None
        assert set(config.network_allowlist) == {"example.com", "*.cdn.net"}

    def test_parse_security_config_normalizes_case(self):
        raw = {"networkAllowlist": ["  EXAMPLE.COM  ", "*.CDN.Net"]}
        config = parse_security_config(raw)
        assert config is not None
        assert set(config.network_allowlist) == {"example.com", "*.cdn.net"}

    def test_parse_security_config_filters_empty(self):
        raw = {"networkAllowlist": ["example.com", "", "  ", "cdn.net"]}
        config = parse_security_config(raw)
        assert config is not None
        assert set(config.network_allowlist) == {"example.com", "cdn.net"}

    def test_parse_security_config_no_allowlist(self):
        raw = {"approvalTimeoutSeconds": 60}
        config = parse_security_config(raw)
        assert config is not None
        assert config.network_allowlist == ()

    def test_evaluate_tool_call_scheme_before_ruleset(self):
        """URL scheme check (L2) runs before permission ruleset (L3),
        so even a permissive ruleset cannot override it."""
        config = SecurityConfig()
        action, reason = evaluate_tool_call("browser_navigate", {"url": "file:///etc/passwd"}, config)
        assert action == PermissionAction.DENY
        assert "file" in reason

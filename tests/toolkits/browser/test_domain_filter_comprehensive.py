"""Comprehensive tests for domain filtering (100% coverage)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.domain_filter import (
    DomainAllowlist,
    build_csp_meta_script,
    build_init_script,
    install_domain_filter,
)

# =============================================================================
# DomainAllowlist
# =============================================================================


class TestDomainAllowlist:
    """Test DomainAllowlist class."""

    def test_init(self) -> None:
        """Test DomainAllowlist initialization."""
        allowlist = DomainAllowlist(patterns=("example.com", "*.github.com"))

        assert allowlist.patterns == ("example.com", "*.github.com")

    def test_from_strings(self) -> None:
        """Test from_strings factory method."""
        allowlist = DomainAllowlist.from_strings(["  Example.COM  ", "*.GitHub.com", ""])

        assert allowlist.patterns == ("example.com", "*.github.com")

    def test_from_strings_empty_list(self) -> None:
        """Test from_strings with empty list."""
        allowlist = DomainAllowlist.from_strings([])

        assert allowlist.patterns == ()
        assert allowlist.is_empty

    def test_from_strings_only_whitespace(self) -> None:
        """Test from_strings filters out whitespace-only strings."""
        allowlist = DomainAllowlist.from_strings(["  ", "\t", "\n", ""])

        assert allowlist.patterns == ()

    def test_is_empty_true(self) -> None:
        """Test is_empty returns True for empty allowlist."""
        allowlist = DomainAllowlist(patterns=())

        assert allowlist.is_empty is True

    def test_is_empty_false(self) -> None:
        """Test is_empty returns False for non-empty allowlist."""
        allowlist = DomainAllowlist(patterns=("example.com",))

        assert allowlist.is_empty is False

    def test_is_allowed_exact_match(self) -> None:
        """Test exact domain match."""
        allowlist = DomainAllowlist(patterns=("example.com",))

        assert allowlist.is_allowed("example.com") is True
        assert allowlist.is_allowed("EXAMPLE.COM") is True
        assert allowlist.is_allowed("other.com") is False

    def test_is_allowed_wildcard_subdomain(self) -> None:
        """Test wildcard subdomain match."""
        allowlist = DomainAllowlist(patterns=("*.example.com",))

        assert allowlist.is_allowed("example.com") is True
        assert allowlist.is_allowed("www.example.com") is True
        assert allowlist.is_allowed("api.example.com") is True
        assert allowlist.is_allowed("other.com") is False

    def test_is_allowed_wildcard_nested_subdomain(self) -> None:
        """Test wildcard match for nested subdomains."""
        allowlist = DomainAllowlist(patterns=("*.github.com",))

        assert allowlist.is_allowed("github.com") is True
        assert allowlist.is_allowed("api.github.com") is True
        assert allowlist.is_allowed("foo.bar.github.com") is True
        assert allowlist.is_allowed("raw.githubusercontent.com") is False

    def test_is_allowed_multiple_patterns(self) -> None:
        """Test multiple patterns."""
        allowlist = DomainAllowlist(patterns=("example.com", "*.github.com", "google.com"))

        assert allowlist.is_allowed("example.com") is True
        assert allowlist.is_allowed("api.github.com") is True
        assert allowlist.is_allowed("google.com") is True
        assert allowlist.is_allowed("facebook.com") is False

    def test_is_allowed_case_insensitive(self) -> None:
        """Test case-insensitive matching."""
        allowlist = DomainAllowlist.from_strings(["Example.COM"])

        assert allowlist.is_allowed("example.com") is True
        assert allowlist.is_allowed("EXAMPLE.COM") is True
        assert allowlist.is_allowed("Example.Com") is True


# =============================================================================
# build_init_script
# =============================================================================


def test_build_csp_meta_script_structure() -> None:
    """Test CSP meta script generates valid structure."""
    allowlist = DomainAllowlist(patterns=("example.com",))

    script = build_csp_meta_script(allowlist)

    assert script.startswith("(function() {")
    assert "createElement('meta')" in script
    assert "Content-Security-Policy" in script
    assert "connect-src" in script
    assert script.strip().endswith("})();")


def test_build_csp_meta_script_includes_domains() -> None:
    """Test CSP script includes allowed domains without protocol prefix."""
    allowlist = DomainAllowlist(patterns=("example.com", "*.github.com"))

    script = build_csp_meta_script(allowlist)

    assert "example.com" in script
    assert "github.com" in script


def test_build_csp_meta_script_directives() -> None:
    """Test CSP includes required directives."""
    allowlist = DomainAllowlist(patterns=("example.com",))

    script = build_csp_meta_script(allowlist)

    assert "connect-src" in script
    assert "script-src" in script
    assert "frame-src" in script
    assert "object-src 'none'" in script
    assert "default-src" not in script


def test_build_csp_meta_script_empty_allowlist() -> None:
    """Test CSP with empty allowlist only allows self."""
    allowlist = DomainAllowlist(patterns=())

    script = build_csp_meta_script(allowlist)

    assert "connect-src 'self'" in script
    assert "script-src 'self'" in script
    assert "frame-src 'self'" in script
    assert "object-src 'none'" in script
    assert "example.com" not in script
    assert "github.com" not in script


def test_build_csp_meta_script_wildcard_domain_expansion() -> None:
    """Test wildcard domain generates both bare and wildcard entries."""
    allowlist = DomainAllowlist(patterns=("*.github.com",))

    script = build_csp_meta_script(allowlist)

    assert "github.com" in script
    assert "*.github.com" in script


def test_build_csp_meta_script_mixed_domains() -> None:
    """Test mix of exact and wildcard domains."""
    allowlist = DomainAllowlist(patterns=("example.com", "*.github.com"))

    script = build_csp_meta_script(allowlist)

    assert "example.com" in script
    assert "github.com" in script
    assert "*.github.com" in script


def test_build_csp_meta_script_no_default_src() -> None:
    """Test CSP does not include default-src to allow CDN resources."""
    allowlist = DomainAllowlist(patterns=("example.com",))

    script = build_csp_meta_script(allowlist)

    assert "default-src" not in script


def test_build_init_script_structure() -> None:
    """Test build_init_script generates valid JavaScript."""
    script = build_init_script()

    assert script.startswith("(function() {")
    assert "_harden" in script
    assert script.strip().endswith("})();")


def test_build_init_script_rtc_patching() -> None:
    """Test script includes RTCPeerConnection patching."""
    script = build_init_script()

    assert "RTCPeerConnection" in script
    assert "SecurityError" in script
    assert "blocked by domain policy" in script


def test_build_init_script_webtransport_patching() -> None:
    """Test script includes WebTransport patching."""
    script = build_init_script()

    assert "WebTransport" in script
    assert "SecurityError" in script


def test_build_init_script_service_worker_disabled() -> None:
    """Test script disables Service Worker registration."""
    script = build_init_script()

    assert "serviceWorker" in script
    assert "register" in script
    assert "Promise.reject" in script


def test_build_init_script_object_define_property() -> None:
    """Test script uses Object.defineProperty for hardening."""
    script = build_init_script()

    assert "Object.defineProperty" in script
    assert "writable: false" in script
    assert "configurable: false" in script


def test_build_init_script_no_domain_logic() -> None:
    """Test script does not include domain checking (delegated to CSP)."""
    script = build_init_script()

    assert "_isAllowed" not in script
    assert "_checkUrl" not in script
    assert "_patterns" not in script
    assert "WebSocket" not in script
    assert "EventSource" not in script
    assert "sendBeacon" not in script


# =============================================================================
# install_domain_filter
# =============================================================================


@pytest.mark.asyncio
async def test_install_domain_filter_empty_allowlist() -> None:
    """Test install_domain_filter skips for empty allowlist."""
    context = MagicMock()
    context.route = AsyncMock()
    context.add_init_script = AsyncMock()
    context.on = MagicMock()

    allowlist = DomainAllowlist(patterns=())

    await install_domain_filter(context, allowlist)

    context.route.assert_not_called()
    context.add_init_script.assert_not_called()


@pytest.mark.asyncio
async def test_install_domain_filter_with_patterns() -> None:
    """Test install_domain_filter installs all four layers."""
    context = MagicMock()
    context.route = AsyncMock()
    context.add_init_script = AsyncMock()
    context.on = MagicMock()

    allowlist = DomainAllowlist(patterns=("example.com",))

    await install_domain_filter(context, allowlist)

    context.route.assert_called_once()
    assert context.add_init_script.call_count == 2

    assert context.on.call_count == 1
    call_args = context.on.call_args
    assert call_args[0][0] == "page"
    assert callable(call_args[0][1])


@pytest.mark.asyncio
async def test_install_domain_filter_without_cdp_audit() -> None:
    """Test install_domain_filter with CDP audit disabled."""
    context = MagicMock()
    context.route = AsyncMock()
    context.add_init_script = AsyncMock()
    context.on = MagicMock()

    allowlist = DomainAllowlist(patterns=("example.com",))

    await install_domain_filter(context, allowlist, enable_cdp_audit=False)

    context.route.assert_called_once()
    assert context.add_init_script.call_count == 2
    context.on.assert_not_called()


# =============================================================================
# Integration test with mocked context
# =============================================================================


@pytest.mark.asyncio
async def test_domain_filter_full_workflow() -> None:
    """Test complete domain filtering workflow."""
    context = MagicMock()
    context.route = AsyncMock()
    context.add_init_script = AsyncMock()
    context.on = MagicMock()

    patterns = ["example.com", "*.github.com", "api.openai.com"]
    allowlist = DomainAllowlist.from_strings(patterns)

    assert not allowlist.is_empty
    assert allowlist.is_allowed("example.com")
    assert allowlist.is_allowed("api.github.com")
    assert allowlist.is_allowed("api.openai.com")
    assert not allowlist.is_allowed("facebook.com")

    await install_domain_filter(context, allowlist, enable_cdp_audit=True)

    context.route.assert_called_once()
    assert context.add_init_script.call_count == 2
    assert context.on.call_count == 1


# =============================================================================
# Edge cases
# =============================================================================


def test_allowlist_frozen() -> None:
    """Test DomainAllowlist is frozen (immutable)."""
    allowlist = DomainAllowlist(patterns=("example.com",))

    with pytest.raises(Exception):
        allowlist.patterns = ("hacked.com",)  # type: ignore[misc]


def test_allowlist_empty_patterns() -> None:
    """Test empty patterns tuple."""
    allowlist = DomainAllowlist(patterns=())

    assert allowlist.is_empty
    assert not allowlist.is_allowed("example.com")


def test_is_allowed_subdomain_not_matching() -> None:
    """Test subdomain of non-wildcard pattern is rejected."""
    allowlist = DomainAllowlist(patterns=("example.com",))

    assert allowlist.is_allowed("example.com") is True
    assert allowlist.is_allowed("www.example.com") is False


def test_is_allowed_wildcard_exact_bare_domain() -> None:
    """Test *.example.com matches bare domain example.com."""
    allowlist = DomainAllowlist(patterns=("*.example.com",))

    assert allowlist.is_allowed("example.com") is True


def test_build_csp_meta_script_special_characters_in_domain() -> None:
    """Test CSP script handles special characters in domains."""
    allowlist = DomainAllowlist(patterns=("example-site.co.uk",))
    script = build_csp_meta_script(allowlist)

    assert "example-site.co.uk" in script


def test_build_csp_meta_script_many_patterns() -> None:
    """Test CSP script with many patterns."""
    patterns = tuple(f"domain{i}.com" for i in range(50))
    allowlist = DomainAllowlist(patterns=patterns)

    script = build_csp_meta_script(allowlist)

    assert "domain0.com" in script
    assert "domain49.com" in script


# =============================================================================
# HTTP filter (_install_http_filter) - Layer 1
# =============================================================================


@pytest.mark.asyncio
async def test_http_filter_blocks_non_allowed_domain() -> None:
    """Test HTTP filter blocks requests to non-allowed domains."""
    from myrm_agent_harness.toolkits.browser.domain_filter import _install_http_filter

    context = MagicMock()
    route_handler = None

    async def capture_handler(pattern: str, handler: Any) -> None:
        nonlocal route_handler
        route_handler = handler

    context.route = capture_handler

    allowlist = DomainAllowlist(patterns=("example.com",))
    await _install_http_filter(context, allowlist)

    assert route_handler is not None

    mock_route = MagicMock()
    mock_route.request.url = "https://blocked.com/path"
    mock_route.request.resource_type = "document"
    mock_route.abort = AsyncMock()
    mock_route.continue_ = AsyncMock()

    await route_handler(mock_route)

    mock_route.abort.assert_called_once_with("blockedbyclient")
    mock_route.continue_.assert_not_called()


@pytest.mark.asyncio
async def test_http_filter_allows_allowed_domain() -> None:
    """Test HTTP filter allows requests to allowed domains."""
    from myrm_agent_harness.toolkits.browser.domain_filter import _install_http_filter

    context = MagicMock()
    route_handler = None

    async def capture_handler(pattern: str, handler: Any) -> None:
        nonlocal route_handler
        route_handler = handler

    context.route = capture_handler

    allowlist = DomainAllowlist(patterns=("example.com",))
    await _install_http_filter(context, allowlist)

    assert route_handler is not None
    mock_route = MagicMock()
    mock_route.request.url = "https://example.com/path"
    mock_route.request.resource_type = "document"
    mock_route.abort = AsyncMock()
    mock_route.continue_ = AsyncMock()

    await route_handler(mock_route)

    mock_route.continue_.assert_called_once()
    mock_route.abort.assert_not_called()


@pytest.mark.asyncio
async def test_http_filter_non_http_document_blocked() -> None:
    """Test HTTP filter blocks non-HTTP document resources."""
    from myrm_agent_harness.toolkits.browser.domain_filter import _install_http_filter

    context = MagicMock()
    route_handler = None

    async def capture_handler(pattern: str, handler: Any) -> None:
        nonlocal route_handler
        route_handler = handler

    context.route = capture_handler

    allowlist = DomainAllowlist(patterns=("example.com",))
    await _install_http_filter(context, allowlist)

    assert route_handler is not None
    mock_route = MagicMock()
    mock_route.request.url = "chrome://version"
    mock_route.request.resource_type = "document"
    mock_route.abort = AsyncMock()
    mock_route.continue_ = AsyncMock()

    await route_handler(mock_route)

    mock_route.abort.assert_called_once_with("blockedbyclient")


@pytest.mark.asyncio
async def test_http_filter_non_http_non_document_allowed() -> None:
    """Test HTTP filter allows non-HTTP non-document resources."""
    from myrm_agent_harness.toolkits.browser.domain_filter import _install_http_filter

    context = MagicMock()
    route_handler = None

    async def capture_handler(pattern: str, handler: Any) -> None:
        nonlocal route_handler
        route_handler = handler

    context.route = capture_handler

    allowlist = DomainAllowlist(patterns=("example.com",))
    await _install_http_filter(context, allowlist)

    assert route_handler is not None
    mock_route = MagicMock()
    mock_route.request.url = "data:text/html,<h1>Test</h1>"
    mock_route.request.resource_type = "image"
    mock_route.abort = AsyncMock()
    mock_route.continue_ = AsyncMock()

    await route_handler(mock_route)

    mock_route.continue_.assert_called_once()


# =============================================================================
# Constructor hardening (_install_constructor_hardening) - Layer 2
# =============================================================================


@pytest.mark.asyncio
async def test_main_thread_hardening_injects_script() -> None:
    """Test main thread hardening injects init script."""
    from myrm_agent_harness.toolkits.browser.domain_filter import _install_main_thread_hardening

    context = MagicMock()
    context.add_init_script = AsyncMock()

    await _install_main_thread_hardening(context)

    context.add_init_script.assert_called_once()
    script = context.add_init_script.call_args[0][0]
    assert "RTCPeerConnection" in script
    assert "serviceWorker" in script


# =============================================================================
# CDP audit (_schedule_cdp_audit, _log_task_exception) - Layer 3
# =============================================================================


def test_schedule_cdp_audit_creates_task() -> None:
    """Test _schedule_cdp_audit creates background task."""
    from unittest.mock import patch

    from myrm_agent_harness.toolkits.browser.domain_filter import _schedule_cdp_audit

    page = MagicMock()
    allowlist = DomainAllowlist(patterns=("example.com",))

    mock_loop = MagicMock()
    mock_task = MagicMock()
    mock_loop.create_task = MagicMock(return_value=mock_task)

    with patch("asyncio.get_running_loop", return_value=mock_loop):
        _schedule_cdp_audit(page, allowlist)

        mock_loop.create_task.assert_called_once()
        mock_task.add_done_callback.assert_called_once()


def test_schedule_cdp_audit_no_running_loop() -> None:
    """Test _schedule_cdp_audit handles no running loop gracefully."""
    from unittest.mock import patch

    from myrm_agent_harness.toolkits.browser.domain_filter import _schedule_cdp_audit

    page = MagicMock()
    allowlist = DomainAllowlist(patterns=("example.com",))

    with patch("asyncio.get_running_loop", side_effect=RuntimeError("No running loop")):
        _schedule_cdp_audit(page, allowlist)


def test_log_task_exception_with_exception() -> None:
    """Test _log_task_exception logs task exceptions."""
    from myrm_agent_harness.toolkits.browser.domain_filter import _log_task_exception

    task = MagicMock()
    task.cancelled = MagicMock(return_value=False)
    task.exception = MagicMock(return_value=RuntimeError("Task failed"))

    _log_task_exception(task)


def test_log_task_exception_cancelled_task() -> None:
    """Test _log_task_exception skips cancelled tasks."""
    from myrm_agent_harness.toolkits.browser.domain_filter import _log_task_exception

    task = MagicMock()
    task.cancelled = MagicMock(return_value=True)

    _log_task_exception(task)

    task.exception.assert_not_called()


def test_log_task_exception_no_exception() -> None:
    """Test _log_task_exception skips tasks without exceptions."""
    from myrm_agent_harness.toolkits.browser.domain_filter import _log_task_exception

    task = MagicMock()
    task.cancelled = MagicMock(return_value=False)
    task.exception = MagicMock(return_value=None)

    _log_task_exception(task)


# =============================================================================
# _install_cdp_audit detailed tests
# =============================================================================


@pytest.mark.asyncio
async def test_install_cdp_audit_enables_network() -> None:
    """Test _install_cdp_audit enables Network domain."""
    from myrm_agent_harness.toolkits.browser.domain_filter import _install_cdp_audit

    page = MagicMock()
    mock_cdp = AsyncMock()
    mock_cdp.send = AsyncMock()
    mock_cdp.on = MagicMock()
    page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)

    allowlist = DomainAllowlist(patterns=("example.com",))

    await _install_cdp_audit(page, allowlist)

    mock_cdp.send.assert_called_with("Network.enable")
    mock_cdp.on.assert_called_once()


@pytest.mark.asyncio
async def test_install_cdp_audit_ws_violation_logging() -> None:
    """Test CDP audit logs WebSocket violations."""
    from myrm_agent_harness.toolkits.browser.domain_filter import _install_cdp_audit

    page = MagicMock()
    mock_cdp = AsyncMock()
    mock_cdp.send = AsyncMock()

    ws_handler = None

    def capture_on(event: str, handler: Any) -> None:
        nonlocal ws_handler
        if event == "Network.webSocketCreated":
            ws_handler = handler

    mock_cdp.on = capture_on
    page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)

    allowlist = DomainAllowlist(patterns=("example.com",))

    await _install_cdp_audit(page, allowlist)

    assert ws_handler is not None

    ws_handler({"url": "wss://evil.com/socket"})


@pytest.mark.asyncio
async def test_install_cdp_audit_exception_handling() -> None:
    """Test _install_cdp_audit handles exceptions gracefully."""
    from myrm_agent_harness.toolkits.browser.domain_filter import _install_cdp_audit

    page = MagicMock()
    page.context.new_cdp_session = AsyncMock(side_effect=RuntimeError("CDP failed"))

    allowlist = DomainAllowlist(patterns=("example.com",))

    await _install_cdp_audit(page, allowlist)

"""
Unit tests for Default Captcha and Confirm Screen Human Handoff Gate Suite.
"""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.core.security.browser_human_handoff import (
    BrowserHumanHandoffGateSuite,
    BrowserLeaseStatus,
    BrowserProfileLeaseManager,
    CaptchaConfirmInterceptor,
    HandoffTriggerType,
    ZeroContentDOMWatchdog,
)


def test_captcha_confirm_interceptor_detection() -> None:
    interceptor = CaptchaConfirmInterceptor()

    # 1. Cloudflare Turnstile
    cf_dom = '<html><body><div class="cf-turnstile" data-sitekey="abc"></div></body></html>'
    res_cf = interceptor.inspect_page(cf_dom, url="https://example.com/login")
    assert res_cf.is_handoff_required is True
    assert res_cf.trigger_type == HandoffTriggerType.CAPTCHA_CHALLENGE
    assert "Turnstile" in res_cf.explanation

    # 2. Confirm Screen
    confirm_dom = '<html><body><button class="btn-confirm">Confirm Order and Pay Now</button></body></html>'
    res_confirm = interceptor.inspect_page(confirm_dom, url="https://checkout.example.com")
    assert res_confirm.is_handoff_required is True
    assert res_confirm.trigger_type == HandoffTriggerType.CONFIRM_SCREEN

    # 3. Clean DOM
    clean_dom = "<html><body><h1>Welcome to My Blog</h1><p>Articles and tips.</p></body></html>"
    res_clean = interceptor.inspect_page(clean_dom, url="https://blog.example.com")
    assert res_clean.is_handoff_required is False
    assert res_clean.is_resolved is True

    # 4. Resolve interception
    pending = interceptor.list_pending_interceptions()
    assert len(pending) == 2
    resolved = interceptor.resolve_interception(res_cf.interception_id)
    assert resolved.is_resolved is True
    assert resolved.is_handoff_required is False
    assert len(interceptor.list_pending_interceptions()) == 1


def test_browser_lease_manager_mutual_exclusion() -> None:
    lease_mgr = BrowserProfileLeaseManager()

    # 1. Acquire lease
    lease1 = lease_mgr.acquire_lease("chrome-main", consumer_id="task-agent-1", ttl_seconds=60.0)
    assert lease1.status == BrowserLeaseStatus.LEASED
    assert lease1.profile_name == "chrome-main"

    # 2. Reject concurrent collision
    with pytest.raises(RuntimeError, match="currently leased by consumer 'task-agent-1'"):
        lease_mgr.acquire_lease("chrome-main", consumer_id="task-agent-2", ttl_seconds=60.0)

    # 3. Release and re-acquire
    released = lease_mgr.release_lease(lease1.lease_id)
    assert released.status == BrowserLeaseStatus.RELEASED

    lease2 = lease_mgr.acquire_lease("chrome-main", consumer_id="task-agent-2", ttl_seconds=60.0)
    assert lease2.consumer_id == "task-agent-2"


def test_browser_lease_manager_ttl_expiry() -> None:
    lease_mgr = BrowserProfileLeaseManager()

    # Acquire lease with 0.1s TTL
    _ = lease_mgr.acquire_lease("edge-finance", consumer_id="task-finance", ttl_seconds=0.1)
    time.sleep(0.15)

    # Active lease query should indicate expiration
    active = lease_mgr.get_active_lease("edge-finance")
    assert active is None

    # Should allow immediate re-acquisition
    new_lease = lease_mgr.acquire_lease("edge-finance", consumer_id="task-finance-2", ttl_seconds=10.0)
    assert new_lease.consumer_id == "task-finance-2"


def test_zero_content_dom_watchdog() -> None:
    watchdog = ZeroContentDOMWatchdog(min_healthy_chars=10, min_healthy_nodes=2)

    # 1. about:blank is permitted
    blank = watchdog.inspect_dom_health("", url="about:blank")
    assert blank.is_corrupted_zero_content is False

    # 2. Zero-character whiteout
    empty_markup = "<html><body>   <div class='spinner'></div> </body></html>"
    stunted = watchdog.inspect_dom_health(empty_markup, url="https://spa-app.com")
    assert stunted.is_corrupted_zero_content is True
    assert "Catastrophic 0-character DOM corruption" in stunted.diagnosis

    # 3. Healthy DOM
    healthy_markup = "<html><body><header>App Header</header><main>Loaded full dashboard content.</main></body></html>"
    healthy = watchdog.inspect_dom_health(healthy_markup, url="https://dashboard.com")
    assert healthy.is_corrupted_zero_content is False


def test_browser_human_handoff_suite_facade() -> None:
    suite = BrowserHumanHandoffGateSuite()

    # 1. Test Captcha Hand-off
    cf_dom = '<html><body><div id="cf-turnstile">Verification Required</div></body></html>'
    interception, _health = suite.inspect_page_safety(cf_dom, url="https://cf.example.com")
    assert interception.is_handoff_required is True
    assert interception.trigger_type == HandoffTriggerType.CAPTCHA_CHALLENGE
    assert suite.metrics.captcha_interceptions_total == 1

    # 2. Test Zero-Content Whiteout
    empty_dom = "<html><body>   </body></html>"
    interception_empty, _ = suite.inspect_page_safety(empty_dom, url="https://frozen.example.com")
    assert interception_empty.is_handoff_required is True
    assert interception_empty.trigger_type == HandoffTriggerType.ZERO_CONTENT_CORRUPTION
    assert suite.metrics.zero_content_corruptions_detected_total == 1

    # 3. Test Lease management via facade
    lease = suite.acquire_profile_lease("profile-alpha", consumer_id="agent-claude", ttl_seconds=100.0)
    assert suite.metrics.browser_leases_granted_total == 1
    assert suite.get_active_lease("profile-alpha") is not None
    assert len(suite.list_active_leases()) == 1

    suite.release_profile_lease(lease.lease_id)
    assert suite.metrics.browser_leases_released_total == 1
    assert suite.get_active_lease("profile-alpha") is None

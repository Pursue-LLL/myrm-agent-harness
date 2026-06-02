"""Test browser toolkit module imports."""


def test_browser_session_imports() -> None:
    """Test that BrowserSession can be imported from browser package."""
    from myrm_agent_harness.toolkits.browser import BrowserSession

    assert BrowserSession is not None


def test_browser_pool_imports() -> None:
    """Test that GlobalBrowserPool and get_global_browser_pool can be imported."""
    from myrm_agent_harness.toolkits.browser.pool import (
        GlobalBrowserPool,
        get_global_browser_pool,
    )

    assert GlobalBrowserPool is not None
    assert get_global_browser_pool is not None


def test_browser_direct_imports() -> None:
    """Test direct imports from browser package."""
    from myrm_agent_harness.toolkits.browser import (
        BrowserSession,
        DomainAllowlist,
        EmulationConfig,
        RetryPolicy,
    )

    assert BrowserSession is not None
    assert DomainAllowlist is not None
    assert EmulationConfig is not None
    assert RetryPolicy is not None

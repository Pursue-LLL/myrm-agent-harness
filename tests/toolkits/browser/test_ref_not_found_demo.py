"""Demo test showing RefNotFoundError structured output for LLM agents."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser import (
    BrowserSession,
    RefNotFoundError,
)
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool

pytestmark = pytest.mark.integration


@pytest.fixture
async def browser_pool() -> GlobalBrowserPool:
    """Create browser pool."""
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=1)
    yield pool
    await pool.shutdown()


@pytest.fixture
async def browser_session(browser_pool: GlobalBrowserPool) -> BrowserSession:
    """Create browser session."""
    session = BrowserSession(browser_pool, ContextType.AGENT)
    yield session
    await session.close()


@pytest.mark.asyncio
async def test_demo_structured_error_output(browser_session: BrowserSession) -> None:
    """Demo: Show the structured error message LLM agents receive.

    This test demonstrates how RefNotFoundError provides rich context
    to help LLM agents self-diagnose and recover from ref invalidation.
    """
    html = """
    <h1>Login Page</h1>
    <input type="text" placeholder="Username" id="username">
    <input type="password" placeholder="Password" id="password">
    <button id="submit">Submit</button>
    <button id="cancel">Cancel</button>
    <a href="/forgot">Forgot password?</a>
    <a href="/signup">Sign up</a>
    """

    await browser_session.new_tab("about:blank")
    await browser_session.evaluate(f"document.body.innerHTML = `{html}`")
    await browser_session.snapshot()

    try:
        await browser_session.interact("click", "e99")
    except RefNotFoundError as e:
        print("\n" + "=" * 70)
        print("RefNotFoundError - Structured Output for LLM Agent:")
        print("=" * 70)
        print(f"\n{e}\n")
        print("Structured Attributes:")
        print(f"  - error.ref: {e.ref}")
        print(f"  - error.total_refs: {e.total_refs}")
        print(f"  - error.ref_range: {e.ref_range}")
        print(f"  - error.context_refs: {e.context_refs}")
        print(f"  - error.context: {e.context}")
        print("\n" + "=" * 70)

        assert e.ref == "e99"
        assert e.total_refs >= 6
        assert len(e.context_refs) >= 4
        assert any("button" in r["role"] for r in e.context_refs)


@pytest.mark.asyncio
async def test_demo_metrics_collection(browser_session: BrowserSession) -> None:
    """Demo: Show how metrics are collected for analysis.

    This test demonstrates the embedded telemetry that helps identify
    if ref invalidation is a real problem requiring automated solutions.
    """
    html = """
    <button>Action 1</button>
    <button>Action 2</button>
    <input type="text" placeholder="Search">
    """

    await browser_session.new_tab("about:blank")
    await browser_session.evaluate(f"document.body.innerHTML = `{html}`")
    await browser_session.snapshot()

    print("\n" + "=" * 70)
    print("Initial Metrics:")
    print("=" * 70)
    stats = browser_session.stats["ref_failures"]
    print(f"  total_failures: {stats['total_failures']}")
    print(f"  top_failed_refs: {stats['top_failed_refs']}")

    for i, invalid_ref in enumerate(["e99", "e98", "e99"], 1):
        try:
            await browser_session.interact("click", invalid_ref)
        except RefNotFoundError:
            print(f"\nAttempt {i}: Failed to interact with {invalid_ref}")

    print("\n" + "=" * 70)
    print("Final Metrics After 3 Failures:")
    print("=" * 70)
    stats = browser_session.stats["ref_failures"]
    print(f"  total_failures: {stats['total_failures']}")
    print(f"  failure_rate: {stats['failure_rate']:.1%}")
    print(f"  recent_failure_rate: {stats['recent_failure_rate']:.1%}")
    print(f"  top_failed_refs: {stats['top_failed_refs']}")
    print("\n" + "=" * 70)

    assert stats["total_failures"] == 3
    assert ("e99", 2) in stats["top_failed_refs"]

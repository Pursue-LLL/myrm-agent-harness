"""Real-browser integration tests for humanized scrolling and CAREFUL click pre-scroll.

Covers the current roadmap deliverables against a real Chromium page:
- Roadmap #1: wheel-input humanized scrolling (DEFAULT burst / CAREFUL rhythm) moves
  the page for real, and no-op scrolls are reported honestly instead of lying.
- scroll_to_bottom reaches the actual container end.
- R1: a CAREFUL click on an off-viewport target first humanized-wheels it into view
  and the click really lands on the element.
- O-A: on a locked-scroll page (body overflow hidden) a CAREFUL click on an
  off-viewport target never silently misses — it either lands via the native
  fallback or fails loudly.
- Edge cases: negative-delta upward scroll, scroll_to_bottom no-overflow early
  exit, and the DEFAULT-mode off-viewport click path (no R1 regression).

The interaction path (wheel events, Bézier mouse, locator actions) is never mocked;
only the in-memory page harness (set_content) is local.

Run: pytest -m integration tests/toolkits/browser/test_interactor_scroll_integration.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.config import (
    HumanizeConfig,
    HumanizeMode,
)
from myrm_agent_harness.toolkits.browser.session.interactor import Interactor
from myrm_agent_harness.toolkits.browser.snapshot import RefInfo

_LONG_PAGE = """<!DOCTYPE html><html><head><style>
html, body { margin: 0; }
#spacer { height: 3000px; }
#deep { position: absolute; top: 2200px; left: 50px; width: 140px; height: 60px; }
</style></head><body>
<div id="spacer"></div>
<button id="deep" onclick="this.dataset.clicked='1'">Deep</button>
</body></html>"""

_LOCKED_PAGE = """<!DOCTYPE html><html><head><style>
html, body { margin: 0; height: 100%; }
body { overflow: hidden; }
#deep { position: absolute; top: 1500px; left: 50px; width: 140px; height: 60px; }
</style></head><body>
<button id="deep" onclick="this.dataset.clicked='1'">Deep</button>
</body></html>"""

_STATIC_PAGE = """<!DOCTYPE html><html><body>
<button id="deep">Deep</button>
</body></html>"""

# Nested scroll container: only #scroller (overflow auto) scrolls; the deep
# button sits 600px inside it, far below its 120px viewport.
_NESTED_PAGE = """<!DOCTYPE html><html><head><style>
html, body { margin: 0; }
#scroller { width: 300px; height: 120px; overflow: auto; border: 1px solid #999; }
#filler { height: 800px; position: relative; }
#deep { position: absolute; top: 600px; left: 20px; width: 100px; height: 40px; }
</style></head><body>
<div id="scroller"><div id="filler"><button id="deep" onclick="this.dataset.clicked='1'">Deep</button></div></div>
</body></html>"""

# Same-origin iframe: the deep button lives inside a scrollable iframe body.
_IFRAME_PAGE = """<!DOCTYPE html><html><head><style>
html, body { margin: 0; }
#f { width: 400px; height: 150px; border: 1px solid #999; }
</style></head><body>
<iframe id="f" srcdoc="<!DOCTYPE html><html><body style=&quot;margin:0&quot;><div style=&quot;height:700px;position:relative&quot;><button id=&quot;deep&quot; onclick=&quot;this.dataset.clicked='1'&quot; style=&quot;position:absolute;top:520px;left:20px&quot;>Deep</button></div></body></html>"></iframe>
</body></html>"""


@pytest.fixture
async def browser() -> GlobalBrowserPool:
    """Real Chromium pool, fresh per test."""
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=1)
    yield pool
    await pool.shutdown()


def _interactor(page: object, mode: HumanizeMode) -> Interactor:
    """Interactor bound to a real page with a single ref (button #deep)."""
    return Interactor(
        page,
        {"e0": RefInfo(role="button", name="Deep", nth=0)},
        humanize=HumanizeConfig.from_mode(mode),
    )


async def _open_page(browser: GlobalBrowserPool, html: str):
    """Acquire a real page, load HTML, return (page, context_key)."""
    page, context_key = await browser.acquire_page(ContextType.AGENT)
    await page.set_content(html)
    return page, context_key


# =============================================================================
# Roadmap #1: humanized wheel scrolling
# =============================================================================


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_scroll_default_burst_moves_page_real(browser: GlobalBrowserPool) -> None:
    """DEFAULT scroll delivers real wheel notches that actually move the page."""
    page, ctx = await _open_page(browser, _LONG_PAGE)
    try:
        interactor = _interactor(page, HumanizeMode.DEFAULT)
        result = await interactor.interact("scroll", "e0", "300")

        assert "Scrolled 300px" in result
        scroll_y = await page.evaluate("window.scrollY")
        assert scroll_y >= 200, f"wheel burst did not move the page: scrollY={scroll_y}"
    finally:
        await browser.release_page(page, ctx)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_scroll_careful_rhythm_moves_page_real(
    browser: GlobalBrowserPool,
) -> None:
    """CAREFUL scroll (accel/cruise/decel notches) still moves the page."""
    page, ctx = await _open_page(browser, _LONG_PAGE)
    try:
        interactor = _interactor(page, HumanizeMode.CAREFUL)
        result = await interactor.interact("scroll", "e0", "300")

        assert "Scrolled 300px" in result
        scroll_y = await page.evaluate("window.scrollY")
        # Overshoot + correction may overshoot slightly past 300; must have moved.
        assert (
            scroll_y >= 150
        ), f"CAREFUL rhythm did not move the page: scrollY={scroll_y}"
    finally:
        await browser.release_page(page, ctx)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_scroll_to_bottom_reaches_end_real(browser: GlobalBrowserPool) -> None:
    """scroll_to_bottom stops only at the real container end."""
    page, ctx = await _open_page(browser, _LONG_PAGE)
    try:
        interactor = _interactor(page, HumanizeMode.DEFAULT)
        result = await interactor.interact("scroll_to_bottom", "e0", "")

        scroll_y = await page.evaluate("window.scrollY")
        max_scroll = await page.evaluate(
            "(document.documentElement.scrollHeight - window.innerHeight)"
        )
        assert (
            scroll_y >= max_scroll - 50
        ), f"scroll_to_bottom did not reach the end: scrollY={scroll_y}, max={max_scroll}\n{result}"
    finally:
        await browser.release_page(page, ctx)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_scroll_no_overflow_reports_honest_noop_real(
    browser: GlobalBrowserPool,
) -> None:
    """A non-scrollable page reports the no-op honestly instead of faking success."""
    page, ctx = await _open_page(browser, _STATIC_PAGE)
    try:
        interactor = _interactor(page, HumanizeMode.DEFAULT)
        result = await interactor.interact("scroll", "e0", "200")

        assert "no scrollable overflow" in result, result
        scroll_y = await page.evaluate("window.scrollY")
        assert scroll_y == 0
    finally:
        await browser.release_page(page, ctx)


# =============================================================================
# R1: CAREFUL pre-interaction scroll-into-view
# =============================================================================


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_careful_click_off_viewport_lands_real(
    browser: GlobalBrowserPool,
) -> None:
    """CAREFUL click on an off-viewport target wheels it in and really hits it."""
    page, ctx = await _open_page(browser, _LONG_PAGE)
    try:
        interactor = _interactor(page, HumanizeMode.CAREFUL)
        result = await interactor.interact("click", "e0")

        assert "Clicked e0" in result, result
        clicked = await page.evaluate("document.getElementById('deep').dataset.clicked")
        assert (
            clicked == "1"
        ), "CAREFUL click on an off-viewport target must actually land"
    finally:
        await browser.release_page(page, ctx)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_careful_click_nested_scroll_container_real(
    browser: GlobalBrowserPool,
) -> None:
    """CAREFUL click wheels the real scroll container (nested div), not the page."""
    page, ctx = await _open_page(browser, _NESTED_PAGE)
    try:
        interactor = _interactor(page, HumanizeMode.CAREFUL)
        result = await interactor.interact("click", "e0")

        assert "Clicked e0" in result, result
        clicked = await page.evaluate("document.getElementById('deep').dataset.clicked")
        scroller_top = await page.evaluate(
            "document.getElementById('scroller').scrollTop"
        )
        assert clicked == "1", "CAREFUL click must land inside the nested container"
        assert (
            scroller_top > 0
        ), "the nested #scroller itself must have been wheel-scrolled"
    finally:
        await browser.release_page(page, ctx)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_careful_click_same_origin_iframe_real(
    browser: GlobalBrowserPool,
) -> None:
    """CAREFUL click on a target inside a same-origin iframe wheels the iframe body."""
    page, ctx = await _open_page(browser, _IFRAME_PAGE)
    try:
        interactor = Interactor(
            page,
            {"f1_e0": RefInfo(role="button", name="Deep", nth=0)},
            humanize=HumanizeConfig.from_mode(HumanizeMode.CAREFUL),
        )
        result = await interactor.interact("click", "f1_e0")

        assert "Clicked f1_e0" in result, result
        clicked = await page.evaluate(
            "document.getElementById('f').contentDocument"
            ".getElementById('deep').dataset.clicked"
        )
        iframe_top = await page.evaluate(
            "document.getElementById('f').contentDocument.scrollingElement.scrollTop"
        )
        assert clicked == "1", "CAREFUL click must land inside the iframe"
        assert iframe_top > 0, "the iframe body itself must have been wheel-scrolled"
    finally:
        await browser.release_page(page, ctx)


# =============================================================================
# O-A: locked-scroll fallback (never a silent edge click)
# =============================================================================


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_careful_click_locked_scroll_never_silent_real(
    browser: GlobalBrowserPool,
) -> None:
    """On a locked-scroll page an off-viewport CAREFUL click either lands or fails loudly."""
    page, ctx = await _open_page(browser, _LOCKED_PAGE)
    try:
        interactor = _interactor(page, HumanizeMode.CAREFUL)
        try:
            result = await interactor.interact("click", "e0")
        except Exception as exc:  # loud failure is the honest outcome
            result = f"raised: {type(exc).__name__}"

        clicked = await page.evaluate("document.getElementById('deep').dataset.clicked")
        assert clicked == "1" or result.startswith(
            "raised:"
        ), f"silent miss on locked scroll: {result}"
    finally:
        await browser.release_page(page, ctx)


# =============================================================================
# Edge-case coverage: negative delta / scroll_to_bottom no-op / DEFAULT no-regression
# =============================================================================


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_scroll_negative_delta_scrolls_up_real(
    browser: GlobalBrowserPool,
) -> None:
    """A negative delta (upward scroll) really moves the page up, not down."""
    page, ctx = await _open_page(browser, _LONG_PAGE)
    try:
        interactor = _interactor(page, HumanizeMode.DEFAULT)
        await interactor.interact("scroll", "e0", "500")
        top_before = await page.evaluate("window.scrollY")
        assert top_before >= 300, f"initial down-scroll did not move: {top_before}"

        result = await interactor.interact("scroll", "e0", "-200")
        assert "Scrolled -200px" in result, result
        top_after = await page.evaluate("window.scrollY")
        assert (
            top_after < top_before
        ), f"negative delta must scroll up: before={top_before}, after={top_after}"
    finally:
        await browser.release_page(page, ctx)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_scroll_to_bottom_no_overflow_early_exit_real(
    browser: GlobalBrowserPool,
) -> None:
    """scroll_to_bottom on a non-scrollable page exits immediately with the honest no-op."""
    page, ctx = await _open_page(browser, _STATIC_PAGE)
    try:
        interactor = _interactor(page, HumanizeMode.DEFAULT)
        result = await interactor.interact("scroll_to_bottom", "e0", "")

        assert "no scrollable overflow" in result, result
        scroll_y = await page.evaluate("window.scrollY")
        assert scroll_y == 0
    finally:
        await browser.release_page(page, ctx)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_default_click_off_viewport_lands_real(
    browser: GlobalBrowserPool,
) -> None:
    """DEFAULT click on an off-viewport target still lands via the native path."""
    page, ctx = await _open_page(browser, _LONG_PAGE)
    try:
        interactor = _interactor(page, HumanizeMode.DEFAULT)
        result = await interactor.interact("click", "e0")

        assert "Clicked e0" in result, result
        clicked = await page.evaluate("document.getElementById('deep').dataset.clicked")
        assert clicked == "1", "DEFAULT click must still land after R1 changes"
    finally:
        await browser.release_page(page, ctx)

"""Real-browser checks for blocking-modal detection.

[INPUT]
- myrm_agent_harness.toolkits.browser.snapshot.element_detectors::detect_blocking_modal

[OUTPUT]
- Regression guards: a plain page never reads as modal-blocked (quirks mode stretches html/body over
  the viewport), and a real dialog keeps its own form fields actionable.

[POS]
Integration tests mirroring src/myrm_agent_harness/toolkits/browser/snapshot/element_detectors.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.element_detectors import detect_blocking_modal

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def page() -> AsyncIterator[object]:
    from patchright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    try:
        yield await browser.new_page()
    finally:
        await browser.close()
        await pw.stop()


async def test_quirks_mode_page_is_not_a_blocking_modal(page: object) -> None:
    await page.set_content('<h1>Login</h1><input type="text" placeholder="Username"><button>Go</button>')

    assert await detect_blocking_modal(page) is None


async def test_dialog_lists_form_fields_by_placeholder_and_label(page: object) -> None:
    await page.set_content(
        "<!DOCTYPE html><html><body><button>Behind</button>"
        '<dialog open aria-modal="true" style="position:fixed;inset:0;width:100%;height:100%">'
        '<input type="text" placeholder="Username">'
        '<label>Email <input type="email"></label>'
        "<button>Submit</button></dialog></body></html>"
    )

    modal = await detect_blocking_modal(page)

    assert modal is not None
    inner = modal["innerInteractive"]
    assert isinstance(inner, list)
    assert {"Username", "Submit"} <= set(inner)
    assert any(name.startswith("Email") for name in inner)

"""Real-browser integration tests for capture_script.js select label resolution.

Injects the actual capture_script.js into a real Chromium page, dispatches
change events on `<select>` elements (and focus/input/blur on inputs) under
various labeling schemes, and asserts the emitted `elementText` follows the
six-level resolution order (aria-label → label[for] → placeholder → wrapping
label → adjacent sibling → selected option).

These tests exercise the shipped resource file end-to-end, so the JS needs no
mock DOM shims.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[4] / "src/myrm_agent_harness/toolkits/browser/action_capture/capture_script.js"
)

Recorder = Callable[[str, str], str | None]


def _load_capture_js() -> str:
    return _SCRIPT_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def capture_js() -> str:
    return _load_capture_js()


@pytest.fixture(scope="module")
def recorder(capture_js: str) -> Recorder:
    """Install the capture script on a real page and return a synchronous driver
    that dispatches DOM events and returns the last captured elementText.

    Patchright's async objects are bound to the event loop that created them,
    so every page operation runs inside a single dedicated background loop
    instead of per-call asyncio.run (which would deadlock on a shared loop).
    """
    import asyncio

    from patchright.async_api import async_playwright

    steps: list[dict[str, Any]] = []
    results: dict[int, tuple[str | None, BaseException | None]] = {}
    _next_key = 0
    start_barrier = threading.Event()

    async def _emit(html: str, tag: str, key: int) -> None:
        pw = None
        browser = None
        try:
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.expose_function("__myrmCaptureCallback", lambda raw: steps.append(json.loads(raw)))
            await page.goto("about:blank")
            await page.evaluate(capture_js)
            assert await page.evaluate("window.__myrmCaptureActive") is True
            if tag == "input":
                await page.evaluate(
                    """(html) => {
                      document.body.innerHTML = html;
                      const el = document.querySelector('input');
                      el.dispatchEvent(new Event('focusin', { bubbles: true }));
                      el.value = 'test value';
                      el.dispatchEvent(new Event('input', { bubbles: true }));
                      el.dispatchEvent(new Event('focusout', { bubbles: true }));
                    }""",
                    html,
                )
            elif tag == "textarea":
                await page.evaluate(
                    """(html) => {
                      document.body.innerHTML = html;
                      const el = document.querySelector('textarea');
                      el.dispatchEvent(new Event('focusin', { bubbles: true }));
                      el.value = 'test value';
                      el.dispatchEvent(new Event('input', { bubbles: true }));
                      el.dispatchEvent(new Event('focusout', { bubbles: true }));
                    }""",
                    html,
                )
            elif tag == "button":
                await page.evaluate(
                    """(html) => {
                      document.body.innerHTML = html;
                      const el = document.querySelector('button');
                      el.dispatchEvent(new MouseEvent('click', { bubbles: true, button: 0 }));
                    }""",
                    html,
                )
            else:
                await page.evaluate(
                    """(payload) => {
                      document.body.innerHTML = payload.html;
                      const el = document.querySelector(payload.tag);
                      el.dispatchEvent(new Event('change', { bubbles: true }));
                    }""",
                    {"html": html, "tag": tag},
                )
            await page.wait_for_timeout(100)
            results[key] = (steps[-1].get("elementText") if steps else None, None)
        except BaseException as exc:  # surfaced to the test thread
            results[key] = (None, exc)
        finally:
            if browser is not None:
                await browser.close()
            if pw is not None:
                await pw.stop()

    def emit_sync(html: str, tag: str = "select") -> str | None:
        nonlocal _next_key
        steps.clear()
        key = _next_key
        _next_key += 1
        loop.call_soon_threadsafe(asyncio.create_task, _emit(html, tag, key))
        deadline = time.monotonic() + 30
        while key not in results:
            if time.monotonic() > deadline:
                raise TimeoutError(f"browser op did not finish within 30s (key={key})")
            time.sleep(0.05)
        value, exc = results.pop(key)
        if exc is not None:
            raise exc
        return value

    # Start the dedicated loop and fail fast if it cannot boot the browser.
    loop = asyncio.new_event_loop()

    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        start_barrier.set()
        loop.run_forever()

    t = threading.Thread(target=_run_loop, daemon=True)
    t.start()
    start_barrier.wait()
    yield emit_sync
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=5)


def test_select_label_for_resolves_field_name(recorder: Recorder) -> None:
    # label[for] association pointing at the select — the field name must win
    # over the concatenated option texts.
    result = recorder(
        """
        <label for="country">Country</label>
        <select id="country">
          <option value="af">Afghanistan</option>
          <option value="ar" selected>Argentina</option>
        </select>
        """
    )
    assert result == "Country"


def test_select_wrapping_label_with_controls_stripped(recorder: Recorder) -> None:
    # A wrapping <label> containing the select — its option texts must not leak
    # into the field name.
    result = recorder(
        """
        <label>
          Preferred
          <select>
            <option value="a">Alpha</option>
            <option value="b" selected>Beta</option>
          </select>
        </label>
        """
    )
    assert result == "Preferred"


def test_select_aria_label_wins_over_label_for(recorder: Recorder) -> None:
    result = recorder(
        """
        <label for="lang">Fallback</label>
        <select id="lang" aria-label="Language">
          <option value="en" selected>English</option>
        </select>
        """
    )
    assert result == "Language"


def test_select_adjacent_span_fallback(recorder: Recorder) -> None:
    # No aria-label / label[for] / wrapping label — adjacent element text used.
    result = recorder(
        """
        <span>Country</span>
        <select>
          <option value="cn" selected>China</option>
        </select>
        """
    )
    assert result == "Country"


def test_select_adjacent_label_fallback(recorder: Recorder) -> None:
    # An adjacent <label> without `for` still describes the select via the
    # sibling-text fallback path.
    result = recorder(
        """
        <label>Country</label>
        <select>
          <option value="cn" selected>China</option>
        </select>
        """
    )
    assert result == "Country"


def test_select_adjacent_div_fallback(recorder: Recorder) -> None:
    result = recorder(
        """
        <div>Country</div>
        <select>
          <option value="cn" selected>China</option>
        </select>
        """
    )
    assert result == "Country"


def test_select_adjacent_non_label_tag_ignored(recorder: Recorder) -> None:
    # A heading next to the select is not a sibling-label signal — falls
    # through to the selected option label.
    result = recorder(
        """
        <h3>Country</h3>
        <select>
          <option value="cn" selected>China</option>
        </select>
        """
    )
    assert result == "China"


def test_select_adjacent_empty_sibling_ignored(recorder: Recorder) -> None:
    # An empty adjacent element yields no text — falls through to the option.
    result = recorder(
        """
        <span></span>
        <select>
          <option value="cn" selected>China</option>
        </select>
        """
    )
    assert result == "China"


def test_select_no_label_uses_selected_option(recorder: Recorder) -> None:
    result = recorder(
        """
        <select>
          <option value="en">English</option>
          <option value="es" selected>Español</option>
        </select>
        """
    )
    assert result == "Español"


def test_select_option_label_attribute_wins(recorder: Recorder) -> None:
    # An explicit `label` attribute on the option is more descriptive than the
    # text node.
    result = recorder(
        """
        <select>
          <option value="a" label="Alpha" selected>AX</option>
        </select>
        """
    )
    assert result == "Alpha"


def test_select_empty_option_returns_empty(recorder: Recorder) -> None:
    # No label source and no selected option text — empty string, never the
    # concatenated option soup.
    result = recorder(
        """
        <select>
          <option value=""></option>
        </select>
        """
    )
    assert result == ""


def test_select_multiple_selected_first_option_label(recorder: Recorder) -> None:
    # For multi-selects the field name falls back to the first selected
    # option's label.
    result = recorder(
        """
        <select multiple>
          <option value="en" selected>English</option>
          <option value="zh" selected>Chinese</option>
        </select>
        """
    )
    assert result == "English"


def test_select_multiline_label_collapsed(recorder: Recorder) -> None:
    # Multi-line label text must be collapsed to a single line.
    result = recorder(
        """
        <label for="tz">
          Time zone
          <small>
            UTC
          </small>
        </label>
        <select id="tz">
          <option value="utc" selected>UTC+0</option>
        </select>
        """
    )
    assert result == "Time zone UTC"


def test_input_label_for_resolves_field_name(recorder: Recorder) -> None:
    # Non-select form controls also benefit from label[for] resolution.
    result = recorder(
        """
        <label for="username">Username</label>
        <input id="username" type="text" />
        """,
        tag="input",
    )
    assert result == "Username"


def test_input_wrapping_label_resolves_field_name(recorder: Recorder) -> None:
    # The classic inline form — <label> wrapping the control with no `for` —
    # must also yield the field name.
    result = recorder(
        """
        <label>Username <input type="text" /></label>
        """,
        tag="input",
    )
    assert result == "Username"


def test_textarea_wrapping_label_resolves_field_name(recorder: Recorder) -> None:
    result = recorder(
        """
        <label>Bio <textarea></textarea></label>
        """,
        tag="textarea",
    )
    assert result == "Bio"


def test_textarea_label_for_resolves_field_name(recorder: Recorder) -> None:
    result = recorder(
        """
        <label for="bio">Bio</label>
        <textarea id="bio"></textarea>
        """,
        tag="textarea",
    )
    assert result == "Bio"


def test_textarea_placeholder_fallback(recorder: Recorder) -> None:
    result = recorder(
        """
        <textarea id="bio" placeholder="Tell us about yourself"></textarea>
        """,
        tag="textarea",
    )
    assert result == "Tell us about yourself"


def test_input_label_for_strips_button_from_label(recorder: Recorder) -> None:
    # Form controls nested inside the label (e.g. a helper button) must not
    # pollute the field name.
    result = recorder(
        """
        <label for="username">Username <button>Check</button></label>
        <input id="username" type="text" />
        """,
        tag="input",
    )
    assert result == "Username"


def test_input_placeholder_fallback(recorder: Recorder) -> None:
    result = recorder(
        """
        <input id="q" placeholder="Search..." />
        """,
        tag="input",
    )
    assert result == "Search..."


def test_input_wrapping_label_beats_placeholder(recorder: Recorder) -> None:
    # A wrapping label is a stronger signal than the placeholder text.
    result = recorder(
        """
        <label>Bio <input type="text" placeholder="hint" /></label>
        """,
        tag="input",
    )
    assert result == "Bio"


def test_input_aria_label_wins(recorder: Recorder) -> None:
    result = recorder(
        """
        <label for="pw">Password</label>
        <input id="pw" type="password" aria-label="Passphrase" />
        """,
        tag="input",
    )
    assert result == "Passphrase"


def test_input_label_for_with_special_char_id(recorder: Recorder) -> None:
    # CSS.escape keeps label[for] working for ids with dots.
    result = recorder(
        """
        <label for="user.name">User Name</label>
        <input id="user.name" type="text" />
        """,
        tag="input",
    )
    assert result == "User Name"


def test_input_long_label_truncated(recorder: Recorder) -> None:
    long_label = "This is a very long field label " * 6
    result = recorder(
        f'<label for="l">{long_label}</label><input id="l" type="text" />',
        tag="input",
    )
    assert result.endswith("...")
    assert len(result) == 83  # 80 chars + "..."


def test_no_label_returns_empty_string(recorder: Recorder) -> None:
    result = recorder(
        """
        <div>
          <input id="bare" type="text" />
        </div>
        """,
        tag="input",
    )
    assert result == ""


def test_button_click_text_content(recorder: Recorder) -> None:
    # Non-form elements fall back to their text content.
    result = recorder(
        """
        <button>Submit Order</button>
        """,
        tag="button",
    )
    assert result == "Submit Order"


def test_button_click_aria_label(recorder: Recorder) -> None:
    result = recorder(
        """
        <button aria-label="Close dialog">X</button>
        """,
        tag="button",
    )
    assert result == "Close dialog"


def test_capture_script_ships_in_package() -> None:
    """Guard against the resource file being renamed or dropped."""
    assert _SCRIPT_PATH.is_file()
    assert re.search(r"function getText\(", _load_capture_js())
    assert "associatedLabelText" in _load_capture_js()
    assert "labelFieldText" in _load_capture_js()

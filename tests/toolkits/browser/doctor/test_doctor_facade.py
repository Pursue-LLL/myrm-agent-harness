"""The browser package's lazy exports must resolve to the same objects the doctor facade exposes."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits import browser
from myrm_agent_harness.toolkits.browser import doctor

_SHARED_SYMBOLS = sorted(set(doctor.__all__) & set(browser.__all__))


def test_browser_package_reexports_doctor_symbols() -> None:
    """The browser package keeps exposing the orphan and report entry points consumed by the server."""
    assert {
        "cleanup_orphan_processes",
        "cleanup_stale_automation_sandboxes",
        "find_orphan_automation_processes",
        "format_report",
        "run_doctor",
    } <= set(_SHARED_SYMBOLS)


@pytest.mark.parametrize("symbol", _SHARED_SYMBOLS)
def test_browser_lazy_export_resolves_to_doctor_facade_object(symbol: str) -> None:
    """A lazy-map entry pointing at a module that no longer defines the symbol must fail here, not in a consumer."""
    assert getattr(browser, symbol) is getattr(doctor, symbol)

"""exclude_capture_windows reaches the backend that captures the screen, whatever wraps it.

A host names its overlay windows once per session. The session's backend chain — a native
backend, or the cua-driver proxy around one — must end up holding exactly those titles, and a
chain with no capable backend must report that instead of failing.

Pure-mock, headless-safe: no Quartz call is made.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

from myrm_agent_harness.api import security as security_facade
from myrm_agent_harness.toolkits.computer_use import exclude_capture_windows
from myrm_agent_harness.toolkits.computer_use.backends import macos as macos_mod
from myrm_agent_harness.toolkits.computer_use.backends.cua_driver import CuaDriverBackend
from myrm_agent_harness.toolkits.computer_use.backends.protocols import ComputerBackend
from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
from myrm_agent_harness.toolkits.computer_use.session import ComputerSession

_CURTAIN = "Privacy Curtain"


def test_titles_reach_a_native_backend() -> None:
    backend = macos_mod.MacOSBackend()
    session = ComputerSession(backend=backend)

    assert exclude_capture_windows(session, [_CURTAIN]) is True
    assert backend._excluded_capture_titles == frozenset({_CURTAIN})


def test_titles_reach_the_native_backend_behind_cua_driver() -> None:
    """The production desktop chain: cua-driver has no capture of its own, its fallback does."""
    native = macos_mod.MacOSBackend()
    session = DesktopSession(backend=CuaDriverBackend(fallback=native))

    assert exclude_capture_windows(session, [_CURTAIN]) is True
    assert native._excluded_capture_titles == frozenset({_CURTAIN})


def test_a_later_call_replaces_the_set_and_any_iterable_is_accepted() -> None:
    backend = macos_mod.MacOSBackend()
    session = ComputerSession(backend=backend)

    def _titles() -> Iterator[str]:
        yield "First"
        yield "Second"

    assert exclude_capture_windows(session, _titles()) is True
    assert backend._excluded_capture_titles == frozenset({"First", "Second"})

    assert exclude_capture_windows(session, (_CURTAIN,)) is True
    assert backend._excluded_capture_titles == frozenset({_CURTAIN})


def test_a_chain_without_a_capable_backend_reports_false() -> None:
    """Every platform but macOS: nothing to inject into, and that is not an error."""
    plain = MagicMock(spec=ComputerBackend)

    assert exclude_capture_windows(ComputerSession(backend=plain), [_CURTAIN]) is False
    assert exclude_capture_windows(ComputerSession(backend=CuaDriverBackend(fallback=plain)), [_CURTAIN]) is False


def test_the_security_facade_re_exports_the_same_function() -> None:
    assert security_facade.exclude_capture_windows is exclude_capture_windows

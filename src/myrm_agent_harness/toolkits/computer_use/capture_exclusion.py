"""Capture exclusion — let a host keep its own overlay windows out of a session's screenshots.

[INPUT]
- session::ComputerSession (POS: session whose platform backend performs the full-screen capture)

[OUTPUT]
- exclude_capture_windows: name the host windows that full-screen captures must look through

[POS]
Public capability for hosts that put an always-on-top window of their own over the desktop (a
privacy curtain). The host names the window titles; a backend that supports it then captures the
desktop beneath those windows and refuses global pointer input while one is on screen
(backends/macos.py). The backend chain is resolved here, inside the package that owns it, so a
host never reaches into private attributes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.computer_use.session import ComputerSession


def exclude_capture_windows(session: ComputerSession, titles: Iterable[str]) -> bool:
    """Hand *titles* to the backend that captures the screen, replacing any earlier set.

    The same titles arm the backend's pointer guard: a global pointer action is refused while
    a window with one of these titles is on screen, because that window would take the click.
    So only a window that captures clicks belongs here; a click-through overlay must stay out.

    Returns False when no backend in the session's chain supports it (every platform but
    macOS). Targeted window captures are never affected and a title with no window on screen
    changes nothing, so calling this unconditionally is safe.
    """
    title_list = list(titles)
    backend: object | None = session._backend
    while backend is not None:
        setter = getattr(backend, "set_excluded_capture_window_titles", None)
        if callable(setter):
            setter(title_list)
            return True
        # CuaDriverBackend delegates screen capture to the native backend it wraps.
        backend = getattr(backend, "_fallback", None)
    return False

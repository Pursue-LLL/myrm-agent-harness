"""Private-network origins a local-mode browser session was explicitly sent to.

[INPUT]
- stdlib urllib.parse

[OUTPUT]
- PrivateOriginGrants: set of origins that may be loaded although they are private

[POS]
Local-mode policy primitive for ``RedirectHopEvaluator``. A local session may browse the user's
own machine, but only where the agent navigated on purpose: a page, redirect or script that merely
sends the browser to a loopback or LAN address is not an instruction to read it. Pure data, no
browser types; the evaluator decides which rules a grant may relax (cloud metadata never).
"""

from __future__ import annotations

from urllib.parse import urlparse

_DEFAULT_PORTS: dict[str, int] = {"http": 80, "https": 443}

type _Origin = tuple[str, str, int]


def _origin_of(url: str) -> _Origin | None:
    """Return (scheme, host, port) for an http(s) URL, or None when the URL has no usable origin."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").rstrip(".").lower()
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    return scheme, host, port or _DEFAULT_PORTS[scheme]


class PrivateOriginGrants:
    """Origins (scheme, host, port) the agent explicitly navigated to."""

    __slots__ = ("_origins",)

    def __init__(self) -> None:
        self._origins: set[_Origin] = set()

    def grant(self, url: str) -> None:
        origin = _origin_of(url)
        if origin is not None:
            self._origins.add(origin)

    def permits(self, url: str) -> bool:
        origin = _origin_of(url)
        return origin is not None and origin in self._origins

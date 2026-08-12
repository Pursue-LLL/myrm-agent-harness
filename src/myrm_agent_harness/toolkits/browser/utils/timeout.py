"""Timeout detection helper for the browser toolkit.

Patchright's ``TimeoutError`` is a distinct class that does not subclass the
builtin ``TimeoutError``, so any code that touches patchright must recognize
both. Centralizing that knowledge here prevents call sites from re-discovering
it or writing fragile ``except TimeoutError`` clauses.
"""

from __future__ import annotations


def is_timeout_error(exc: BaseException) -> bool:
    """Return True when ``exc`` is a builtin or patchright timeout.

    patchright is imported lazily so importing this module never requires the
    optional ``[browser]`` extra to be installed.
    """
    from patchright.async_api import TimeoutError as PlaywrightTimeoutError

    return isinstance(exc, (TimeoutError, PlaywrightTimeoutError))

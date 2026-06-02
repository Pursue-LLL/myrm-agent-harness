"""Encrypted session save/restore API for BrowserSession.

[INPUT]
- (none)

[OUTPUT]
- BrowserSessionPersistenceMixin: save_session / restore_session / list / delete when Sessi...
- require_persistence: decorator: check SessionPersistence whetheralreadyconfigu...

[POS]
Encrypted session save/restore API for BrowserSession.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import ParamSpec

P = ParamSpec("P")


def require_persistence[**P](func: Callable[P, Awaitable[str]]) -> Callable[P, Awaitable[str]]:
    """decorator: check SessionPersistence whetheralreadyconfiguration

    if self._persistence as None, returnerror messagenotisexecutesmethod.
    """

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        self = args[0]
        if self._persistence is None:
            return "Error: SessionVault not configured for this BrowserSession"
        return await func(*args, **kwargs)

    return wrapper


class BrowserSessionPersistenceMixin:
    """save_session / restore_session / list / delete when SessionVault is configured."""

    @require_persistence
    async def save_session(self, domain: str) -> str:
        """save session state toencryptstorage"""
        from ..backends.file_backend import is_valid_domain_name

        if not is_valid_domain_name(domain):
            return (
                f"Error: Invalid domain name: {domain!r}. Only [a-zA-Z0-9._-:] allowed, no path traversal (.., /, \\)"
            )

        await self._ensure_components()
        page = self._tab_controller.get_active_page()
        context = page.context

        result = await self._persistence.save(context, domain)

        if not result.startswith("Error:"):
            session_hash = await self._persistence.compute_hash(domain)
            if session_hash:
                self._session_hash_cache[domain] = session_hash

        return result

    @require_persistence
    async def restore_session(self, domain: str) -> str:
        """fromencryptstoragerestoresessionstate"""
        from ..backends.file_backend import is_valid_domain_name

        if not is_valid_domain_name(domain):
            return (
                f"Error: Invalid domain name: {domain!r}. Only [a-zA-Z0-9._-:] allowed, no path traversal (.., /, \\)"
            )

        await self._ensure_components()
        page = self._tab_controller.get_active_page()
        context = page.context

        return await self._persistence.restore(context, page, domain)

    @require_persistence
    async def list_sessions(self) -> str:
        """list all savedsession"""
        return await self._persistence.list_domains()

    @require_persistence
    async def delete_session(self, domain: str) -> str:
        """deletesave'ssession"""
        from ..backends.file_backend import is_valid_domain_name

        if not is_valid_domain_name(domain):
            return (
                f"Error: Invalid domain name: {domain!r}. Only [a-zA-Z0-9._-:] allowed, no path traversal (.., /, \\)"
            )

        return await self._persistence.delete(domain)

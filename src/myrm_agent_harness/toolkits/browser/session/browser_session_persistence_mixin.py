"""Encrypted session save/restore API for BrowserSession.

[INPUT]
- session.session_lifecycle_hook::SessionLifecycleHookProtocol (POS: optional observer for session events)

[OUTPUT]
- BrowserSessionPersistenceMixin: save_session / restore_session / list / delete when SessionVault is configured.
- require_persistence: decorator: check SessionPersistence is configured.

[POS]
Encrypted session save/restore API for BrowserSession. Fires optional
``SessionLifecycleHookProtocol`` callbacks on save/delete so external
systems (e.g. the memory system) can react without coupling.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, ParamSpec

if TYPE_CHECKING:
    from .session_lifecycle_hook import SessionLifecycleHookProtocol
    from .session_persistence import SessionPersistence
    from .tab_controller import TabController

P = ParamSpec("P")
logger = logging.getLogger(__name__)


def require_persistence[**P](func: Callable[P, Awaitable[str]]) -> Callable[P, Awaitable[str]]:
    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        self = args[0]
        if getattr(self, "_persistence", None) is None:
            return "Error: SessionVault not configured for this BrowserSession"
        return await func(*args, **kwargs)

    return wrapper


def _fire_and_forget(coro: Awaitable[object]) -> None:
    """Schedule a coroutine as a fire-and-forget background task."""

    def _log_exception(t: asyncio.Task[object]) -> None:
        if not t.cancelled():
            exc = t.exception()
            if exc is not None:
                logger.warning("SessionLifecycleHook fire-and-forget failed: %s", exc)

    task = asyncio.ensure_future(coro)
    task.add_done_callback(_log_exception)


class BrowserSessionPersistenceMixin:
    """save_session / restore_session / list / delete when SessionVault is configured."""

    _session_lifecycle_hook: SessionLifecycleHookProtocol | None
    _persistence: SessionPersistence | None
    _tab_controller: TabController
    _session_hash_cache: dict[str, str]

    def set_session_lifecycle_hook(self, hook: SessionLifecycleHookProtocol) -> None:
        """Inject an optional lifecycle observer (e.g. SessionMemoryBridge)."""
        self._session_lifecycle_hook = hook

    @require_persistence
    async def save_session(self, domain: str) -> str:
        from ..session_vault.backends.file_backend import is_valid_domain_name

        if not is_valid_domain_name(domain):
            return (
                f"Error: Invalid domain name: {domain!r}. Only [a-zA-Z0-9._-:] allowed, no path traversal (.., /, \\)"
            )

        await self._ensure_components()
        page = self._tab_controller.get_active_page()
        context = page.context

        assert self._persistence is not None  # require_persistence guards this
        result = await self._persistence.save(context, domain)

        if not result.startswith("Error:"):
            session_hash = await self._persistence.compute_hash(domain)
            if session_hash:
                self._session_hash_cache[domain] = session_hash

            hook = getattr(self, "_session_lifecycle_hook", None)
            if hook is not None:
                cookie_count, ls_count = _parse_counts(result)
                _fire_and_forget(hook.on_session_saved(domain, cookie_count, ls_count))

        return result

    @require_persistence
    async def restore_session(self, domain: str) -> str:
        from ..session_vault.backends.file_backend import is_valid_domain_name

        if not is_valid_domain_name(domain):
            return (
                f"Error: Invalid domain name: {domain!r}. Only [a-zA-Z0-9._-:] allowed, no path traversal (.., /, \\)"
            )

        await self._ensure_components()
        page = self._tab_controller.get_active_page()

        assert self._persistence is not None  # require_persistence guards this
        return await self._persistence.restore(page.context, domain)

    @require_persistence
    async def list_sessions(self) -> str:
        assert self._persistence is not None  # require_persistence guards this
        return await self._persistence.list_domains()

    @require_persistence
    async def delete_session(self, domain: str) -> str:
        from ..session_vault.backends.file_backend import is_valid_domain_name

        if not is_valid_domain_name(domain):
            return (
                f"Error: Invalid domain name: {domain!r}. Only [a-zA-Z0-9._-:] allowed, no path traversal (.., /, \\)"
            )

        assert self._persistence is not None  # require_persistence guards this
        result = await self._persistence.delete(domain)
        if not result.startswith("Error:") and "No saved session" not in result:
            hook = getattr(self, "_session_lifecycle_hook", None)
            if hook is not None:
                _fire_and_forget(hook.on_session_deleted(domain))

        return result


_RE_COOKIES = re.compile(r"(\d+)\s+cookies")
_RE_LOCAL_STORAGE = re.compile(r"(\d+)\s+localStorage")


def _parse_counts(save_result: str) -> tuple[int, int]:
    """Extract cookie/localStorage counts from SessionPersistence.save() output.

    Expected format: ``'Saved encrypted session for X (N cookies, M localStorage items)'``
    """
    cookie_match = _RE_COOKIES.search(save_result)
    ls_match = _RE_LOCAL_STORAGE.search(save_result)
    return (
        int(cookie_match.group(1)) if cookie_match else 0,
        int(ls_match.group(1)) if ls_match else 0,
    )

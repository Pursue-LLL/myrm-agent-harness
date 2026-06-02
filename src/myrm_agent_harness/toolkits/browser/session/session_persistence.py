"""Session persistence operations using encrypted SessionVault.


[INPUT]
- session_vault::SessionVault (POS: AES-256-GCM encrypted session storage)
- patchright.async_api::BrowserContext (POS: browser context)
- patchright.async_api::Page (POS: page instance)

[OUTPUT]
- SessionPersistence: session persistence helper class
  - save(context, domain) -> str: save encrypted session
  - restore(context, page, domain) -> str: restore encrypted session
  - list_domains() -> str: list all sessions
  - delete(domain) -> str: delete session
  - cleanup_expired() -> int: clean up expired sessions
  - compute_hash(domain) -> str | None: compute session state hash

[POS]
Session persistence helper class. Single responsibility: handles session save/restore/list/delete operations.
Includes cookie domain filtering, localStorage injection, and expired session cleanup logic.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext, Page

    from ..session_vault import SessionVault

logger = logging.getLogger(__name__)


class SessionPersistence:
    """Session持久化操作辅助类

    职责:
    1. SaveSessionState(cookies + localStorage)
    2. RestoreSessionState(Auto过期Check)
    3. 列出/DeleteSession
    4. Cookie DomainFilter
    5. 过期SessionClean up
    """

    def __init__(self, vault: SessionVault):
        """InitializeSession持久化操作

        Args:
            vault: SessionVault Instance
        """
        self._vault = vault

    async def save(self, context: BrowserContext, domain: str) -> str:
        """SaveSessionState to EncryptStorage

         using  AES-256-GCM Encrypt,Default 30 天 TTL。
        AutoFilter Cookie:只保留目标Domainrelated  Cookie(Support子DomainMatch)。

        Args:
            context: BrowserContext Instance
            domain: Domain

        Returns:
            操作ResultDescription
        """
        import time

        start_time = time.time()

        try:
            storage_state = await context.storage_state()
        except Exception as exc:
            logger.error("Failed to get storage state for %s: %s", domain, exc)
            return f"Error: Failed to retrieve browser storage state: {exc}"

        total_cookies = len(storage_state.get("cookies", []))
        filtered_cookies = [
            cookie
            for cookie in storage_state.get("cookies", [])
            if self._is_cookie_for_domain(cookie.get("domain", ""), domain)
        ]
        storage_state["cookies"] = filtered_cookies

        local_storage_count = sum(len(origin.get("localStorage", [])) for origin in storage_state.get("origins", []))

        try:
            await self._vault.save(
                domain=domain,
                storage_state=storage_state,
            )
        except Exception as exc:
            logger.error("Failed to save session for %s: %s", domain, exc)
            return f"Error: Failed to save session: {exc}"

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "SessionPersistence: saved session for %s - "
            "%d/%d cookies (filtered), %d localStorage items, elapsed=%.1fms",
            domain,
            len(filtered_cookies),
            total_cookies,
            local_storage_count,
            elapsed_ms,
        )

        return (
            f"Saved encrypted session for {domain} "
            f"({len(filtered_cookies)} cookies, {local_storage_count} localStorage items)"
        )

    async def restore(self, context: BrowserContext, page: Page, domain: str) -> str:
        """ from EncryptStorageRestoreSessionState

        AutoFilter过期Session(Default 30 天 TTL)。

        Args:
            context: BrowserContext Instance
            page: Page Instance( for 注入 localStorage)
            domain: Domain

        Returns:
            操作ResultDescription
        """
        import time

        start_time = time.time()

        try:
            entry = await self._vault.load(domain)
        except Exception as exc:
            logger.error("Failed to load session for %s: %s", domain, exc)
            return f"Error: Failed to load session: {exc}"

        if entry is None:
            return f"No saved session found for domain: {domain} (or session expired)"

        cookies = entry.storage_state.get("cookies", [])
        try:
            await context.add_cookies(cookies)
        except Exception as exc:
            logger.error("Failed to inject cookies for %s: %s", domain, exc)
            return f"Error: Failed to inject cookies: {exc}"

        local_storage_count = 0
        local_storage_origins = entry.storage_state.get("origins", [])
        if local_storage_origins:
            try:
                # 动态分配一个临时页面用于执行同源 localStorage 注入，防止作用在 about:blank 上
                temp_page = await context.new_page()
                # 拦截所有请求，直接返回 200 OK 空页面，实现毫秒级伪导航，避免真实的昂贵网络请求
                await temp_page.route("**/*", lambda route: route.fulfill(status=200, body=""))
                for origin_data in local_storage_origins:
                    origin = origin_data.get("origin")
                    local_storage = origin_data.get("localStorage", [])
                    if local_storage and origin:
                        try:
                            # 导航到目标 origin（被拦截，瞬间返回）以获取正确的执行上下文
                            await temp_page.goto(origin, timeout=5000)
                            await temp_page.evaluate(
                                "(items) => items.forEach(({name, value}) => localStorage.setItem(name, value))",
                                local_storage,
                            )
                            local_storage_count += len(local_storage)
                        except Exception as exc:
                            logger.warning("Failed to inject localStorage for %s (origin %s): %s", domain, origin, exc)
                await temp_page.unroute("**/*")
                await temp_page.close()
            except Exception as exc:
                logger.warning("Failed to process localStorage injection for %s: %s", domain, exc)

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "SessionPersistence: restored session for %s - %d cookies, %d localStorage items, elapsed=%.1fms",
            domain,
            len(cookies),
            local_storage_count,
            elapsed_ms,
        )

        return f"Restored encrypted session for {domain} ({len(cookies)} cookies, {local_storage_count} localStorage items)"

    async def list_domains(self) -> str:
        """列出AllSave Session

        Returns:
            SessionListDescription
        """
        domains = await self._vault.list_domains()

        if not domains:
            return "No saved sessions"

        return "Saved sessions:\n" + "\n".join(f"- {d}" for d in domains)

    async def delete(self, domain: str) -> str:
        """DeleteSave Session

        Args:
            domain: Domain

        Returns:
            操作ResultDescription
        """
        deleted = await self._vault.delete(domain)

        if deleted:
            logger.info("SessionPersistence: deleted encrypted session for %s", domain)
            return f"Deleted encrypted session for {domain}"
        else:
            return f"No saved session found for domain: {domain}"

    async def cleanup_expired(self) -> int:
        """Clean up过期 Session

        Returns:
            Clean up SessionCount
        """
        try:
            removed = await self._vault.cleanup_expired()
            if removed > 0:
                logger.info("SessionPersistence: cleaned up %d expired session(s)", removed)
            return removed
        except Exception as exc:
            logger.warning(f"SessionPersistence: failed to cleanup expired sessions: {exc}")
            return 0

    async def compute_hash(self, domain: str) -> str | None:
        """Compute SHA-256 hash of stored session state.

        Args:
            domain: Session domain

        Returns:
            Hex-encoded hash string, or None if session not found
        """
        import hashlib

        try:
            entry = await self._vault.load(domain)
            if entry is None:
                return None

            import orjson

            storage_json = orjson.dumps(entry.storage_state, option=orjson.OPT_SORT_KEYS)
            return hashlib.sha256(storage_json).hexdigest()
        except Exception as exc:
            logger.error("Failed to compute session hash for %s: %s", domain, exc)
            return None

    @staticmethod
    def _is_cookie_for_domain(cookie_domain: str, target_domain: str) -> bool:
        """Check Cookie Whether属于目标Domain

        Support子DomainMatch(leading dot):
        - .github.com Match github.com  and  api.github.com
        - github.com 只Match github.com

        Args:
            cookie_domain: Cookie   domain Field
            target_domain: 目标Domain

        Returns:
            True IfMatch
        """
        cookie_domain = cookie_domain.lower().strip()
        target_domain = target_domain.lower().strip()

        if cookie_domain.startswith("."):
            return target_domain.endswith(cookie_domain[1:]) or target_domain == cookie_domain[1:]
        return cookie_domain == target_domain

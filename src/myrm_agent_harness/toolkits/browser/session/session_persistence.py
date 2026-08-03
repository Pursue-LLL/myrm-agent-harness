"""Session persistence operations using encrypted SessionVault.


[INPUT]
- session_vault::SessionVault (POS: AES-256-GCM encrypted session storage)
- patchright.async_api::BrowserContext (POS: browser context)
- checkpoint.session_state::normalize_cookies, _build_localstorage_script (POS: cookie/localStorage normalisation)

[OUTPUT]
- SessionPersistence: encrypted session persistence helper
  - save(context, domain) -> str: save encrypted session (domain-filtered cookies)
  - restore(context, domain) -> str: restore encrypted session (normalised cookies + origin-guarded localStorage)
  - list_domains() -> str: list all sessions
  - delete(domain) -> str: delete session
  - cleanup_expired() -> int: clean up expired sessions
  - compute_hash(domain) -> str | None: compute session state hash

[POS]
Encrypted session persistence. Handles save/restore/list/delete with cookie domain filtering,
normalised cookie injection (expires/sameSite), and origin-guarded localStorage via add_init_script.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext

    from ..session_vault import SessionVault

logger = logging.getLogger(__name__)


class SessionPersistence:
    """Encrypted session persistence helper.

    Responsibilities:
    1. Save session state (cookies + localStorage) with AES-256-GCM encryption
    2. Restore session state with automatic expiration check
    3. List / delete saved sessions
    4. Cookie domain filtering (keep only target domain cookies)
    5. Expired session cleanup
    """

    def __init__(self, vault: SessionVault):
        """Initialize session persistence operations.

        Args:
            vault: SessionVault instance for encrypted storage.
        """
        self._vault = vault

    async def save(self, context: BrowserContext, domain: str) -> str:
        """Save session state to encrypted storage.

        Uses AES-256-GCM encryption with a default 30-day TTL.
        Auto-filters cookies to keep only those matching the target domain
        (including subdomain matching).

        Args:
            context: Browser context to extract state from.
            domain: Target domain for cookie filtering.

        Returns:
            Operation result description.
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

    async def restore(self, context: BrowserContext, domain: str) -> str:
        """Restore session state from encrypted storage.

        Auto-filters expired sessions (default 30-day TTL).
        Cookies are normalised (expires/sameSite) before injection.
        localStorage is injected via ``add_init_script`` (zero network I/O).

        Args:
            context: Browser context to inject state into.
            domain: Target domain.

        Returns:
            Operation result description.
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

        from ..checkpoint.session_state import _build_localstorage_script, normalize_cookies

        cookies = normalize_cookies(entry.storage_state.get("cookies", []))
        try:
            await context.add_cookies(cookies)
        except Exception as exc:
            logger.error("Failed to inject cookies for %s: %s", domain, exc)
            return f"Error: Failed to inject cookies: {exc}"

        local_storage_count = 0
        local_storage_origins = entry.storage_state.get("origins", [])
        for origin_data in local_storage_origins:
            origin = origin_data.get("origin")
            local_storage = origin_data.get("localStorage", [])
            if local_storage and origin:
                try:
                    js_code = _build_localstorage_script(local_storage, origin)
                    await context.add_init_script(js_code)
                    local_storage_count += len(local_storage)
                except Exception as exc:
                    logger.warning("Failed to inject localStorage for %s (origin %s): %s", domain, origin, exc)

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
        """List all saved session domains.

        Returns:
            Formatted session list description.
        """
        domains = await self._vault.list_domains()

        if not domains:
            return "No saved sessions"

        return "Saved sessions:\n" + "\n".join(f"- {d}" for d in domains)

    async def delete(self, domain: str) -> str:
        """Delete a saved session.

        Args:
            domain: Target domain.

        Returns:
            Operation result description.
        """
        deleted = await self._vault.delete(domain)

        if deleted:
            logger.info("SessionPersistence: deleted encrypted session for %s", domain)
            return f"Deleted encrypted session for {domain}"
        else:
            return f"No saved session found for domain: {domain}"

    async def cleanup_expired(self) -> int:
        """Remove all expired sessions.

        Returns:
            Number of sessions removed.
        """
        try:
            removed = await self._vault.cleanup_expired()
            if removed > 0:
                logger.info("SessionPersistence: cleaned up %d expired session(s)", removed)
            return removed
        except Exception as exc:
            logger.warning("SessionPersistence: failed to cleanup expired sessions: %s", exc)
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
        """Check if a cookie belongs to the target domain.

        Supports subdomain matching via leading dot:
        - .github.com matches github.com and api.github.com
        - github.com matches only github.com

        Args:
            cookie_domain: Cookie's domain field.
            target_domain: Target domain to match against.

        Returns:
            True if the cookie belongs to the target domain.
        """
        cookie_domain = cookie_domain.lower().strip()
        target_domain = target_domain.lower().strip()

        if cookie_domain.startswith("."):
            return target_domain.endswith(cookie_domain[1:]) or target_domain == cookie_domain[1:]
        return cookie_domain == target_domain

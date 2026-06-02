"""Browser session state tracking for checkpoint/resume.

Provides utilities to extract and restore browser session state via checkpoint metadata.


[INPUT]
- session::BrowserSession (POS: browser session manager)
- session_vault::SessionVault (POS: AES-256-GCM encrypted session storage)
- metadata::CheckpointMetadata, extract_metadata_from_messages (POS: metadata structure)

[OUTPUT]
- get_browser_state: Extract browser state from BrowserSession (uses cached hash)
- restore_browser_state: Restore browser state to BrowserSession
- apply_storage_state: Apply Playwright storage state to BrowserContext

[POS]
Browser session state tracking module. Provides utility functions for extracting and restoring browser state,
supports checkpoint metadata read/write and SessionVault incremental save decisions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from ..session import BrowserSession
    from ..session_vault import SessionVault
    from .metadata import CheckpointMetadata


class BrowserState(TypedDict, total=False):
    """Extracted browser state for checkpoint metadata."""

    current_url: str
    session_domain: str
    session_hash: str
    task_counters: dict[str, int]


class PlaywrightStorageState(TypedDict, total=False):
    """Playwright browser context storage state."""

    cookies: list[dict[str, str]]
    origins: list[dict[str, object]]


logger = logging.getLogger(__name__)


async def get_browser_state(
    session: BrowserSession,
    session_vault: SessionVault | None = None,
) -> BrowserState:
    """Extract browser state from BrowserSession for checkpoint metadata.

    Args:
        session: BrowserSession instance
        session_vault: Optional SessionVault for hash computation

    Returns:
        Dictionary with browser state (current_url, session_domain, session_hash)
    """
    state: BrowserState = {}

    # Extract current URL from active tab
    try:
        if session.list_tabs():
            page = session._tab_controller.get_active_page()
            state["current_url"] = page.url
    except Exception as exc:
        logger.debug("Failed to get current URL: %s", exc)

    # Get cached session hash (memory read, no I/O)
    if session_vault:
        import re

        url = state.get("current_url", "")
        match = re.match(r"https?://([^/]+)", url)
        if match:
            domain = match.group(1)
            state["session_domain"] = domain

            hash_val = session.get_session_hash(domain)
            if hash_val:
                state["session_hash"] = hash_val

    return state


async def restore_browser_state(
    session: BrowserSession,
    metadata: CheckpointMetadata,
    session_vault: SessionVault | None = None,
) -> bool:
    """Restore browser state from checkpoint metadata.

    Args:
        session: Target BrowserSession
        metadata: Checkpoint metadata
        session_vault: Optional SessionVault for session restoration

    Returns:
        True if restoration succeeded
    """
    try:
        # 1. Restore Session Vault (if available)
        if session_vault and metadata.get("session_domain"):
            domain = metadata["session_domain"]
            entry = await session_vault.load(domain)

            if entry:
                # Apply storage state to browser context
                await apply_storage_state(session, entry.storage_state)
                logger.info("Recovery: session restored for %s", domain)
            else:
                logger.warning("Recovery: no session found for %s", domain)

        # 2. Navigate to last URL
        if metadata.get("current_url"):
            url = metadata["current_url"]
            await session.new_tab(url)
            logger.info("Recovery: navigated to %s", url)

        # 3. Take snapshot to refresh ref mappings
        await session.snapshot()

        return True
    except Exception as exc:
        logger.error("Failed to restore browser state: %s", exc, exc_info=True)
        return False


async def apply_storage_state(
    session: BrowserSession,
    storage_state: PlaywrightStorageState,
    *,
    apply_cookies: bool = True,
    apply_localstorage: bool = True,
) -> None:
    """Apply Playwright storage state to BrowserContext.

    Args:
        session: Target BrowserSession
        storage_state: Playwright storage state (cookies + localStorage)
        apply_cookies: Whether to apply cookies (default True)
        apply_localstorage: Whether to apply localStorage (default True)

    Raises:
        RuntimeError: If browser context is not available
    """
    if not hasattr(session, "_context") or session._context is None:
        raise RuntimeError("BrowserContext not available in session")

    context = session._context

    # 1. Add cookies (can be applied anytime)
    if apply_cookies:
        cookies = storage_state.get("cookies", [])
        if cookies:
            await context.add_cookies(cookies)
            logger.debug("Applied %d cookies to browser context", len(cookies))

    # 2. Set localStorage for each origin
    if apply_localstorage:
        origins = storage_state.get("origins", [])
        if not origins:
            return

        # Use context.add_init_script (applies to all pages, including future tabs)
        for origin_data in origins:
            origin = origin_data.get("origin")
            local_storage = origin_data.get("localStorage", [])

            if not origin or not local_storage:
                continue

            js_code = _build_localstorage_script(local_storage)

            try:
                await context.add_init_script(js_code)
                logger.debug(
                    "Applied %d localStorage items for %s (all pages)",
                    len(local_storage),
                    origin,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to apply localStorage for %s: %s",
                    origin,
                    exc,
                )


def _build_localstorage_script(items: list[dict[str, str]]) -> str:
    """Build JavaScript to set localStorage items.

    Args:
        items: List of {name, value} pairs

    Returns:
        JavaScript code
    """
    lines = []
    for item in items:
        name = item.get("name", "")
        value = item.get("value", "")
        if name:
            # Escape quotes for JavaScript string literals
            name_escaped = name.replace("\\", "\\\\").replace('"', '\\"')
            value_escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'localStorage.setItem("{name_escaped}", "{value_escaped}");')

    return "\n".join(lines)

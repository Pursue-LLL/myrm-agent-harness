"""Browser session state tracking for checkpoint/resume.

Provides utilities to extract and restore browser session state via checkpoint metadata.


[INPUT]
- session::BrowserSession (POS: browser session manager)
- session_vault::SessionVault (POS: AES-256-GCM encrypted session storage)
- metadata::CheckpointMetadata, extract_metadata_from_messages (POS: metadata structure)

[OUTPUT]
- normalize_cookies: Sanitize Playwright cookies (expires ≤ 0, sameSite Title Case) for safe re-injection
- get_browser_state: Extract browser state from BrowserSession (uses cached hash)
- restore_browser_state: Restore browser state to BrowserSession
- apply_storage_state: Apply Playwright storage state to BrowserContext
- _build_localstorage_script: Build origin-guarded JS for localStorage injection via add_init_script

[POS]
Browser session state tracking and cookie/localStorage normalisation module. Single normalisation point
for all three cookie-injection paths (session_persistence, checkpoint, lifecycle).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypedDict

from myrm_agent_harness.core.security.redact import redact_sensitive_text

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

_SAMESITE_CANONICAL = {"strict": "Strict", "lax": "Lax", "none": "None"}


def normalize_cookies(cookies: list[dict[str, object]]) -> list[dict[str, object]]:
    """Sanitize cookies exported by Playwright for safe re-injection.

    Playwright ``context.storage_state()`` exports session cookies with
    ``expires: -1`` or ``0``.  When passed back to ``context.add_cookies()``,
    ``expires=0`` is interpreted as *"already expired"* and the cookie is
    silently dropped.  Additionally, ``sameSite`` may arrive in lowercase
    (``none``/``lax``/``strict``) but ``add_cookies`` expects Title Case.

    This function is the **single normalisation point** used by all three
    cookie-injection paths (session_persistence, checkpoint, lifecycle).
    """
    out: list[dict[str, object]] = []
    for cookie in cookies:
        c = dict(cookie)
        exp = c.get("expires")
        if isinstance(exp, (int, float)) and exp <= 0:
            c.pop("expires", None)
        ss = c.get("sameSite")
        if isinstance(ss, str):
            c["sameSite"] = _SAMESITE_CANONICAL.get(ss.lower(), ss)
        out.append(c)
    return out


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
            logger.info(
                "Recovery: navigated to %s", redact_sensitive_text(url)[:80]
            )

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

    # 1. Add cookies (normalized to avoid expires/sameSite pitfalls)
    if apply_cookies:
        cookies = normalize_cookies(storage_state.get("cookies", []))
        if cookies:
            await context.add_cookies(cookies)
            logger.debug("Applied %d cookies to browser context", len(cookies))

    # 2. Set localStorage for each origin via init scripts
    if apply_localstorage:
        origins = storage_state.get("origins", [])
        if not origins:
            return

        for origin_data in origins:
            origin = origin_data.get("origin")
            local_storage = origin_data.get("localStorage", [])

            if not origin or not local_storage:
                continue

            js_code = _build_localstorage_script(local_storage, origin)

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


def _build_localstorage_script(
    items: list[dict[str, str]],
    origin: str | None = None,
) -> str:
    """Build JavaScript to set localStorage items with optional origin guard.

    Uses ``JSON.parse`` for safe serialisation (immune to injection via
    malicious key/value content).

    Args:
        items: List of ``{name, value}`` pairs.
        origin: When provided, the script only executes on pages whose
            ``window.location.origin`` matches this value.

    Returns:
        Self-executing JavaScript code string.
    """
    import json

    payload = json.dumps(items)
    origin_json = json.dumps(origin) if origin else None

    if origin_json:
        return (
            f"(() => {{\n"
            f"  if (window.location.origin === {origin_json}) {{\n"
            f"    JSON.parse({json.dumps(payload)}).forEach("
            f"({{name, value}}) => localStorage.setItem(name, value));\n"
            f"  }}\n"
            f"}})();"
        )
    return (
        f"(() => {{\n"
        f"  JSON.parse({json.dumps(payload)}).forEach("
        f"({{name, value}}) => localStorage.setItem(name, value));\n"
        f"}})();"
    )

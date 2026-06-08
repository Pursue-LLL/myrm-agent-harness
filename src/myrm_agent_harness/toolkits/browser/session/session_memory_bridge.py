"""Bridge between browser session lifecycle and the agent memory system.

When a browser session is saved, deleted, or expired, this bridge updates a
compact profile attribute (``active_browser_sessions``) so the Agent always
knows which login sessions are available — **without** any extra tool call.

The profile attribute is auto-injected by ``memory_context_middleware`` into
every LLM turn as part of ``<user_memory_context> / Global User Profile``,
giving the Agent zero-cost awareness of available browser identities.

[INPUT]
- session.session_lifecycle_hook::SessionLifecycleHookProtocol (POS: optional observer for session events)
- memory.manager::MemoryManager (POS: stable public import path for the memory toolkit façade)

[OUTPUT]
- SessionMemoryBridge: SessionLifecycleHookProtocol implementation that keeps
  the ``active_browser_sessions`` profile attribute in sync with the vault.

[POS]
Session–memory bridge. Implements SessionLifecycleHookProtocol to maintain a
compact profile attribute that tells the Agent which encrypted login sessions
exist, enabling cross-session identity reuse at zero extra inference cost.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

PROFILE_KEY = "active_browser_sessions"
_MAX_TRACKED_SESSIONS = 10


def _format_entry(domain: str) -> str:
    date_str = datetime.now(timezone.utc).strftime("%b %d")
    return f"{domain} ({date_str})"


def _parse_entries(raw: str | None) -> list[tuple[str, str]]:
    """Parse ``'domain1 (Jun 08), domain2 (Jun 05)'`` into ``[(domain, full), ...]``."""
    if not raw:
        return []
    entries: list[tuple[str, str]] = []
    for part in raw.split(", "):
        part = part.strip()
        if not part:
            continue
        paren = part.find(" (")
        domain = part[:paren] if paren > 0 else part
        entries.append((domain, part))
    return entries


def _serialize(entries: list[tuple[str, str]]) -> str:
    return ", ".join(entry for _, entry in entries)


class SessionMemoryBridge:
    """Keeps ``active_browser_sessions`` profile attribute in sync with the vault.

    All hook methods are fire-and-forget: exceptions are logged, never raised.
    """

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._mm = memory_manager

    # ── SessionLifecycleHookProtocol ────────────────────────────────────

    async def on_session_saved(self, domain: str, cookie_count: int, local_storage_count: int) -> None:
        try:
            current = await self._mm.get_profile_attribute(PROFILE_KEY)
            entries = _parse_entries(current)

            entries = [(d, e) for d, e in entries if d != domain]
            entries.insert(0, (domain, _format_entry(domain)))

            if len(entries) > _MAX_TRACKED_SESSIONS:
                entries = entries[:_MAX_TRACKED_SESSIONS]

            await self._mm.set_system_profile_attribute(PROFILE_KEY, _serialize(entries))
            logger.info("SessionMemoryBridge: profile updated — saved %s (%d tracked)", domain, len(entries))
        except Exception:
            logger.warning("SessionMemoryBridge: failed to update profile after saving %s", domain, exc_info=True)

    async def on_session_deleted(self, domain: str) -> None:
        try:
            current = await self._mm.get_profile_attribute(PROFILE_KEY)
            entries = _parse_entries(current)

            new_entries = [(d, e) for d, e in entries if d != domain]
            if len(new_entries) == len(entries):
                return

            if new_entries:
                await self._mm.set_system_profile_attribute(PROFILE_KEY, _serialize(new_entries))
            else:
                await self._mm.delete_system_profile_attribute(PROFILE_KEY)

            logger.info("SessionMemoryBridge: profile updated — deleted %s", domain)
        except Exception:
            logger.warning("SessionMemoryBridge: failed to update profile after deleting %s", domain, exc_info=True)

    async def on_sessions_expired(self, domains: list[str]) -> None:
        try:
            current = await self._mm.get_profile_attribute(PROFILE_KEY)
            entries = _parse_entries(current)

            expired_set = set(domains)
            new_entries = [(d, e) for d, e in entries if d not in expired_set]
            if len(new_entries) == len(entries):
                return

            if new_entries:
                await self._mm.set_system_profile_attribute(PROFILE_KEY, _serialize(new_entries))
            else:
                await self._mm.delete_system_profile_attribute(PROFILE_KEY)

            logger.info(
                "SessionMemoryBridge: profile updated — expired %d sessions (%s)",
                len(domains),
                ", ".join(domains),
            )
        except Exception:
            logger.warning("SessionMemoryBridge: failed to update profile after expiry", exc_info=True)

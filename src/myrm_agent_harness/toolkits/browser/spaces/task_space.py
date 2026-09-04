"""Browser task space entity for multi-tenant and multi-subagent isolated execution.

Each TaskSpace encapsulates an independent BrowserContext, a dedicated BrowserSession,
an asyncio.Lock for race-condition prevention, and active lifecycle tracking.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext
    from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession


@dataclass
class BrowserTaskSpace:
    """Isolated browser execution workspace with exclusive context and concurrency lock."""

    space_id: str
    name: str = ""
    context: BrowserContext | None = None
    session: BrowserSession | None = None
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)
    is_active: bool = True
    metadata: dict[str, object] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def touch(self) -> None:
        """Update last accessed timestamp to prevent idle timeout eviction."""
        self.last_accessed_at = time.time()

    async def close(self) -> None:
        """Cleanly tear down the encapsulated session and browser context."""
        self.is_active = False
        if self.session is not None:
            try:
                await self.session.close()
            except Exception:  # noqa: S110 - best-effort teardown
                pass
            finally:
                self.session = None

        if self.context is not None:
            try:
                await self.context.close()
            except Exception:  # noqa: S110 - best-effort teardown
                pass
            finally:
                self.context = None

    def to_dict(self) -> dict[str, object]:
        """Serialize space status for observability and UI display."""
        active_pages_count = 0
        if self.context is not None:
            try:
                active_pages_count = len(self.context.pages)
            except Exception:
                active_pages_count = 0

        return {
            "space_id": self.space_id,
            "name": self.name or self.space_id,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "last_accessed_at": self.last_accessed_at,
            "idle_seconds": round(time.time() - self.last_accessed_at, 1),
            "active_pages": active_pages_count,
            "metadata": self.metadata,
        }

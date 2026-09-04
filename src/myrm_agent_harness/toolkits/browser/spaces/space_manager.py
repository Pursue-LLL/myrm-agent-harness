"""Manager for parallel browser task spaces with quota enforcement and idle pruning.

[INPUT]
- .task_space::BrowserTaskSpace (POS: 任务空间隔离实体)
- session.browser_session::BrowserSession (POS: 浏览器会话聚合根)
- patchright.async_api::BrowserContext (POS: 底层浏览器上下文)

[OUTPUT]
- HarnessTaskSpaceManager: 浏览器任务空间多实例管理器

[POS]
浏览器任务空间管理器。管理 TaskSpace 的创建、路由寻址、并发互斥、硬配额保护与超时自动清理。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from .task_space import BrowserTaskSpace

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext
    from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession

logger = logging.getLogger(__name__)


class HarnessTaskSpaceManager:
    """Manages creation, routing, concurrency lock, and lifecycle of BrowserTaskSpaces."""

    def __init__(
        self,
        max_active_spaces: int = 5,
        default_idle_ttl_seconds: float = 900.0,
    ) -> None:
        self.max_active_spaces = max_active_spaces
        self.default_idle_ttl_seconds = default_idle_ttl_seconds
        self._spaces: dict[str, BrowserTaskSpace] = {}
        self._lock = asyncio.Lock()

    async def get_or_create_space(
        self,
        space_id: str,
        name: str | None = None,
        context_factory: Callable[[], Awaitable[BrowserContext]] | None = None,
        session_factory: Callable[[BrowserContext], Awaitable[BrowserSession]] | None = None,
    ) -> BrowserTaskSpace:
        """Retrieve existing space or construct an isolated workspace under quota constraints."""
        async with self._lock:
            existing = self._spaces.get(space_id)
            if existing is not None and existing.is_active:
                existing.touch()
                return existing

            # Enforce active quota
            active_count = sum(1 for s in self._spaces.values() if s.is_active)
            if active_count >= self.max_active_spaces:
                # Attempt to free idle spaces before raising quota error
                pruned = await self._prune_idle_locked(self.default_idle_ttl_seconds)
                active_count = sum(1 for s in self._spaces.values() if s.is_active)
                if active_count >= self.max_active_spaces:
                    raise RuntimeError(
                        f"Active BrowserTaskSpace limit reached ({self.max_active_spaces}). "
                        f"Free an existing space before creating '{space_id}'. (Pruned: {pruned})"
                    )

            context: BrowserContext | None = None
            session: BrowserSession | None = None
            if context_factory is not None:
                context = await context_factory()
                if session_factory is not None and context is not None:
                    session = await session_factory(context)

            space = BrowserTaskSpace(
                space_id=space_id,
                name=name or space_id,
                context=context,
                session=session,
            )
            self._spaces[space_id] = space
            logger.info("Allocated new BrowserTaskSpace '%s' (active: %d)", space_id, active_count + 1)
            return space

    def get_space(self, space_id: str) -> BrowserTaskSpace | None:
        """Lookup an active space and update access time."""
        space = self._spaces.get(space_id)
        if space is not None and space.is_active:
            space.touch()
            return space
        return None

    def list_spaces(self) -> list[BrowserTaskSpace]:
        """Return all active spaces."""
        return [s for s in self._spaces.values() if s.is_active]

    async def close_space(self, space_id: str) -> bool:
        """Gracefully release and unregister a space."""
        async with self._lock:
            space = self._spaces.pop(space_id, None)
            if space is not None:
                await space.close()
                logger.info("Closed BrowserTaskSpace '%s'", space_id)
                return True
            return False

    async def prune_idle_spaces(self, max_idle_seconds: float | None = None) -> int:
        """Scan and close spaces that exceeded their idle TTL."""
        ttl = max_idle_seconds if max_idle_seconds is not None else self.default_idle_ttl_seconds
        async with self._lock:
            return await self._prune_idle_locked(ttl)

    async def _prune_idle_locked(self, ttl: float) -> int:
        now = time.time()
        to_prune: list[str] = []
        for space_id, space in self._spaces.items():
            if space.is_active and (now - space.last_accessed_at) >= ttl:
                to_prune.append(space_id)

        for space_id in to_prune:
            space = self._spaces.pop(space_id)
            await space.close()
            logger.info("Evicted idle BrowserTaskSpace '%s' (idle >= %0.1fs)", space_id, ttl)

        return len(to_prune)

    async def close_all(self) -> None:
        """Shutdown and release all allocated spaces."""
        async with self._lock:
            spaces = list(self._spaces.values())
            self._spaces.clear()
            for space in spaces:
                await space.close()
            logger.info("Tore down all %d BrowserTaskSpaces", len(spaces))

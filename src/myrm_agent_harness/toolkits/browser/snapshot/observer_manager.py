"""MutationObserver management for change detection.

[INPUT]
- (none)

[OUTPUT]
- ObserverManager: class — Observer Manager

[POS]
MutationObserver management for change detection.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from ..exceptions import AriaCrossOriginError
from .observer_scripts import MUTATION_OBSERVER_SCRIPT

if TYPE_CHECKING:
    from patchright.async_api import Frame, Page

logger = logging.getLogger(__name__)


class ObserverManager:
    """MutationObserver 管理器

    职责：
    - 安装 and 卸载 MutationObserver
    - 检测跨域 iframe
    - Get DOM 变化Record
    """

    def __init__(self, frame: Page | Frame):
        """Initialize Observer 管理器

        Args:
            frame: Page  or  Frame Instance
        """
        self._frame = frame
        self._installed = False
        self._is_cross_origin = False

    async def install(self) -> None:
        """安装 MutationObserver  to  Frame"""
        try:
            await asyncio.wait_for(self._frame.evaluate(MUTATION_OBSERVER_SCRIPT), timeout=2.0)
            self._installed = True
            logger.info("MutationObserver installed")
        except Exception as exc:
            error = AriaCrossOriginError(
                "Failed to install observer (likely cross-origin)",
                cause=exc,
            )
            logger.warning(str(error))
            self._is_cross_origin = True
            self._installed = False

    async def get_changes(self) -> list[dict[str, str]]:
        """Get DOM 变化Record

        Returns:
            变化List，Format: [{type, target, ...}]
        """
        try:
            changes = await asyncio.wait_for(
                self._frame.evaluate("() => window.__ariaObserver ? window.__ariaObserver.getChanges() : []"),
                timeout=1.0,
            )
            return changes if isinstance(changes, list) else []
        except Exception as exc:
            logger.warning(f"Failed to get changes: {exc}")
            return []

    async def disconnect(self) -> None:
        """断开 MutationObserver"""
        if self._installed and not self._is_cross_origin:
            with contextlib.suppress(Exception):
                await self._frame.evaluate("() => window.__ariaObserver && window.__ariaObserver.disconnect()")

    def reset(self) -> None:
        """ResetState"""
        self._installed = False
        self._is_cross_origin = False

    @property
    def is_installed(self) -> bool:
        """Check observer Whether already 安装"""
        return self._installed

    @property
    def is_cross_origin(self) -> bool:
        """CheckWhether is 跨域 iframe"""
        return self._is_cross_origin

"""Headless Graceful Degradation Extension UI Context Implementation.

[INPUT]
- ExtensionUIContext from .base_ui_context
- UISelectOption, UINotifyLevel from .ui_types

[OUTPUT]
- HeadlessUIContext

[POS]
Graceful degradation driver for headless environments (cron jobs, CI/CD, batch background workers).
Returns safe policy defaults immediately without hanging execution threads.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from .base_ui_context import ExtensionUIContext
from .ui_types import UINotifyLevel, UISelectOption

logger = logging.getLogger(__name__)


class HeadlessUIContext(ExtensionUIContext):
    """Graceful degradation implementation for headless / non-interactive environments.

    Uses deterministic safe policy defaults:
    - select: returns provided default, or the first option value if available, else empty string.
    - confirm: returns provided default (defaulting to False).
    - input: returns provided default.
    - editor: returns provided content without modifications.
    - notify: logs message to system logger.
    """

    def __init__(self, fallback_confirm: bool = False) -> None:
        self.fallback_confirm = fallback_confirm

    async def select(
        self,
        title: str,
        options: Sequence[UISelectOption],
        default: str | None = None,
        timeout_s: float = 60.0,
    ) -> str:
        del timeout_s
        if default is not None:
            logger.info("[HeadlessUIContext] select '%s' degraded to default: '%s'", title, default)
            return default
        if options:
            selected = options[0].value
            logger.info("[HeadlessUIContext] select '%s' degraded to first option: '%s'", title, selected)
            return selected
        logger.warning("[HeadlessUIContext] select '%s' called with empty options; degraded to empty string", title)
        return ""

    async def confirm(
        self,
        title: str,
        message: str,
        default: bool = False,
        timeout_s: float = 60.0,
    ) -> bool:
        del timeout_s
        result = default if default is not None else self.fallback_confirm
        logger.info("[HeadlessUIContext] confirm '%s' ('%s') degraded to: %s", title, message, result)
        return result

    async def input(
        self,
        title: str,
        placeholder: str = "",
        default: str = "",
        timeout_s: float = 60.0,
    ) -> str:
        del placeholder, timeout_s
        logger.info("[HeadlessUIContext] input '%s' degraded to default: '%s'", title, default)
        return default

    async def editor(
        self,
        title: str,
        content: str,
        language: str = "text",
        timeout_s: float = 300.0,
    ) -> str:
        del language, timeout_s
        logger.info("[HeadlessUIContext] editor '%s' degraded to untouched content (%d chars)", title, len(content))
        return content

    async def notify(
        self,
        message: str,
        level: UINotifyLevel = "info",
    ) -> None:
        if level == "error":
            logger.error("[HeadlessUIContext] notify: %s", message)
        elif level == "warning":
            logger.warning("[HeadlessUIContext] notify: %s", message)
        else:
            logger.info("[HeadlessUIContext] notify: %s", message)

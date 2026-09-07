"""Application lifecycle and package manager for Android devices.

[INPUT]
- types.py, protocols.py, device_manager.py

[OUTPUT]
- MobileAppManager

[POS]
Handles package launches with alias resolution (e.g. 'wechat' -> 'com.tencent.mm'), force stop, and app enumeration.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .protocols import MobileAppManagerProtocol

logger = logging.getLogger(__name__)

COMMON_APP_ALIASES: dict[str, str] = {
    "wechat": "com.tencent.mm",
    "weixin": "com.tencent.mm",
    "feishu": "com.ss.android.lark",
    "lark": "com.ss.android.lark",
    "wework": "com.tencent.wework",
    "dingtalk": "com.alibaba.android.rimet",
    "chrome": "com.android.chrome",
    "browser": "com.android.browser",
    "settings": "com.android.settings",
    "camera": "com.android.camera",
    "gallery": "com.android.gallery3d",
}


class MobileAppManager(MobileAppManagerProtocol):
    """Manages application launch and lifecycle on Android devices."""

    def __init__(self, device_manager: Any) -> None:
        self.dm = device_manager

    async def launch_app(self, serial: str, package_or_alias: str) -> bool:
        """Launch application using monkey launcher to bypass explicit Activity discovery."""
        target_pkg = COMMON_APP_ALIASES.get(package_or_alias.lower(), package_or_alias)

        # Monkey tool launches the default launcher intent reliably
        cmd = f"monkey -p {target_pkg} -c android.intent.category.LAUNCHER 1"
        out = await self.dm.execute_shell(serial, cmd)

        if "Events injected: 1" in out:
            logger.info("Successfully launched app %s on %s", target_pkg, serial)
            return True

        # Fallback to am start if monkey fails
        am_cmd = f"am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n {target_pkg}"
        out_am = await self.dm.execute_shell(serial, am_cmd)
        return "Error" not in out_am

    async def stop_app(self, serial: str, package_name: str) -> bool:
        """Force stop package."""
        target_pkg = COMMON_APP_ALIASES.get(package_name.lower(), package_name)
        out = await self.dm.execute_shell(serial, f"am force-stop {target_pkg}")
        return "Error" not in out

    async def list_installed_apps(self, serial: str, third_party_only: bool = True) -> list[str]:
        """List package names of installed applications."""
        flag = "-3" if third_party_only else ""
        out = await self.dm.execute_shell(serial, f"pm list packages {flag}".strip())
        packages = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                packages.append(line.replace("package:", ""))
        return packages

"""Mobile application lifecycle and intent manager.

[INPUT]
- types::MobileActionResult
- protocols::MobileAppManagerProtocol
- device_manager::MobileDeviceManager

[OUTPUT]
- MobileAppManager: Launches apps by package or alias, terminates packages, inspects foreground Activity

[POS]
App lifecycle controller in toolkits/mobile.
"""

from __future__ import annotations

import logging
import re

from myrm_agent_harness.toolkits.mobile.device_manager import MobileDeviceManager
from myrm_agent_harness.toolkits.mobile.protocols import MobileAppManagerProtocol
from myrm_agent_harness.toolkits.mobile.types import MobileActionResult

logger = logging.getLogger(__name__)

# Common app package aliases for zero-guess launching
COMMON_APP_ALIASES: dict[str, str] = {
    "wechat": "com.tencent.mm",
    "weixin": "com.tencent.mm",
    "微信": "com.tencent.mm",
    "feishu": "com.ss.android.lark",
    "lark": "com.ss.android.lark",
    "飞书": "com.ss.android.lark",
    "dingtalk": "com.alibaba.android.rimet",
    "钉钉": "com.alibaba.android.rimet",
    "settings": "com.android.settings",
    "设置": "com.android.settings",
    "browser": "com.android.chrome",
    "chrome": "com.android.chrome",
    "浏览器": "com.android.chrome",
    "camera": "com.android.camera",
    "相机": "com.android.camera",
    "contacts": "com.android.contacts",
    "通讯录": "com.android.contacts",
    "messages": "com.google.android.apps.messaging",
    "短信": "com.google.android.apps.messaging",
    "alipay": "com.eg.android.AlipayGphone",
    "支付宝": "com.eg.android.AlipayGphone",
    "taobao": "com.taobao.taobao",
    "淘宝": "com.taobao.taobao",
    "meituan": "com.sankuai.meituan",
    "美团": "com.sankuai.meituan",
}


class MobileAppManager(MobileAppManagerProtocol):
    """Manages application startup, termination, and foreground inspection."""

    def __init__(self, device_manager: MobileDeviceManager) -> None:
        self.device_manager = device_manager

    def resolve_package_name(self, package_or_alias: str) -> str:
        """Resolve friendly alias to actual Android package name."""
        cleaned = package_or_alias.strip().lower()
        return COMMON_APP_ALIASES.get(cleaned, package_or_alias.strip())

    async def launch_app(
        self,
        package_or_alias: str,
        activity: str | None = None,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Launch Android application via monkey or am start."""
        device = await self.device_manager.ensure_active_device(serial)
        pkg = self.resolve_package_name(package_or_alias)

        if activity:
            target = f"{pkg}/{activity}" if not activity.startswith(pkg) else activity
            code, stdout, stderr = await self.device_manager._run_adb(
                "-s", device.serial, "shell", "am", "start", "-n", target
            )
        else:
            # Use monkey tool to launch default main activity
            code, stdout, stderr = await self.device_manager._run_adb(
                "-s",
                device.serial,
                "shell",
                "monkey",
                "-p",
                pkg,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            )

        success = code == 0 and "Events injected: 1" in (stdout + stderr) or code == 0
        return MobileActionResult(
            success=success,
            action="launch_app",
            message=f"Launched app '{pkg}'" if success else (stderr or stdout),
            exit_code=code,
            data={"package": pkg, "activity": activity or ""},
        )

    async def terminate_app(
        self,
        package_name: str,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Force stop target package via `am force-stop`."""
        device = await self.device_manager.ensure_active_device(serial)
        pkg = self.resolve_package_name(package_name)

        code, stdout, stderr = await self.device_manager._run_adb(
            "-s", device.serial, "shell", "am", "force-stop", pkg
        )
        return MobileActionResult(
            success=code == 0,
            action="terminate_app",
            message=f"Terminated app '{pkg}'" if code == 0 else stderr,
            exit_code=code,
            data={"package": pkg},
        )

    async def get_current_app(self, serial: str | None = None) -> tuple[str, str]:
        """Detect active foreground package and Activity."""
        device = await self.device_manager.ensure_active_device(serial)
        code, stdout, _ = await self.device_manager._run_adb(
            "-s", device.serial, "shell", "dumpsys", "window", "displays"
        )
        if code == 0 and "mCurrentFocus" in stdout:
            match = re.search(r"mCurrentFocus=Window\{[^}]* ([\w\.]+)/([\w\.]+)\}", stdout)
            if match:
                return match.group(1), match.group(2)

        # Fallback dumpsys activity
        code, stdout, _ = await self.device_manager._run_adb(
            "-s", device.serial, "shell", "dumpsys", "activity", "activities"
        )
        if code == 0:
            match = re.search(r"mResumedActivity: ActivityRecord\{[^}]* ([\w\.]+)/([\w\.]+)", stdout)
            if match:
                return match.group(1), match.group(2)

        return "Unknown", "Unknown"

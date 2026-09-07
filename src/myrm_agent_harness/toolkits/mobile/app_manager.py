"""Mobile Application Lifecycle Manager.

[INPUT]
- types::MobileActionResult (POS: shared mobile types)
- protocols::MobileAppManagerProtocol (POS: app manager contract)

[OUTPUT]
- MobileAppManager: Implementation of package launching, activity introspection and process termination

[POS]
App launching and package discovery engine.
"""

from __future__ import annotations

import logging
import re
import time

from myrm_agent_harness.toolkits.mobile.device_manager import MobileDeviceManager
from myrm_agent_harness.toolkits.mobile.types import MobileActionResult

logger = logging.getLogger(__name__)

# Common app package mappings for seamless semantic launch
_COMMON_APP_ALIASES: dict[str, str] = {
    "wechat": "com.tencent.mm",
    "weixin": "com.tencent.mm",
    "微信": "com.tencent.mm",
    "qq": "com.tencent.mobileqq",
    "feishu": "com.ss.android.lark",
    "lark": "com.ss.android.lark",
    "飞书": "com.ss.android.lark",
    "dingtalk": "com.alibaba.android.rimet",
    "钉钉": "com.alibaba.android.rimet",
    "settings": "com.android.settings",
    "设置": "com.android.settings",
    "chrome": "com.android.chrome",
    "browser": "com.android.browser",
    "camera": "com.android.camera",
    "相机": "com.android.camera",
    "gallery": "com.android.gallery3d",
    "相册": "com.android.gallery3d",
}


class MobileAppManager:
    """Launches, stops, and lists Android apps by package or semantic alias."""

    def __init__(self, device_manager: MobileDeviceManager) -> None:
        self._device_manager = device_manager

    async def launch_app(
        self,
        package_or_alias: str,
        activity: str | None = None,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Launch app by package name or alias (e.g. 'settings', 'wechat')."""
        t0 = time.monotonic()
        target_pkg = _COMMON_APP_ALIASES.get(package_or_alias.lower().strip(), package_or_alias.strip())

        if activity:
            cmp_target = f"{target_pkg}/{activity}"
            args = ["shell", "am", "start", "-n", cmp_target]
        else:
            # Launch via monkey/intent fallback to trigger main launcher activity
            args = [
                "shell",
                "monkey",
                "-p",
                target_pkg,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ]

        code, stdout, stderr = await self._device_manager.execute_adb_command(args, serial=serial)
        dur = int((time.monotonic() - t0) * 1000)
        out_str = stdout.decode("utf-8", errors="ignore")

        if code == 0 and "No activities found" not in out_str:
            return MobileActionResult(
                success=True,
                action=f"launch_app({target_pkg})",
                output=f"Launched application '{target_pkg}'",
                duration_ms=dur,
            )

        # Fallback to am start with intent resolution
        fallback_args = ["shell", "am", "start", "-a", "android.intent.action.MAIN", "-p", target_pkg]
        fb_code, fb_out, fb_err = await self._device_manager.execute_adb_command(fallback_args, serial=serial)
        if fb_code == 0:
            return MobileActionResult(
                success=True,
                action=f"launch_app({target_pkg})",
                output=f"Launched application '{target_pkg}' via MAIN intent",
                duration_ms=dur,
            )

        err_msg = stderr.decode("utf-8", errors="ignore") or fb_err.decode("utf-8", errors="ignore")
        return MobileActionResult(
            success=False,
            action=f"launch_app({target_pkg})",
            error=err_msg or f"Could not launch '{target_pkg}'",
            duration_ms=dur,
        )

    async def stop_app(self, package_name: str, serial: str | None = None) -> MobileActionResult:
        """Force-stop application."""
        t0 = time.monotonic()
        target_pkg = _COMMON_APP_ALIASES.get(package_name.lower().strip(), package_name.strip())
        code, stdout, stderr = await self._device_manager.execute_adb_command(
            ["shell", "am", "force-stop", target_pkg], serial=serial
        )
        dur = int((time.monotonic() - t0) * 1000)
        return MobileActionResult(
            success=code == 0,
            action=f"stop_app({target_pkg})",
            output=f"Stopped package '{target_pkg}'",
            error=stderr.decode("utf-8", errors="ignore") if code != 0 else None,
            duration_ms=dur,
        )

    async def list_installed_packages(
        self, third_party_only: bool = True, serial: str | None = None
    ) -> list[str]:
        """List packages installed on device."""
        flag = "-3" if third_party_only else ""
        args = ["shell", "pm", "list", "packages"]
        if flag:
            args.append(flag)

        code, stdout, _ = await self._device_manager.execute_adb_command(args, serial=serial)
        if code != 0:
            return []

        packages: list[str] = []
        for line in stdout.decode("utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("package:"):
                packages.append(line.replace("package:", "").strip())
        return packages

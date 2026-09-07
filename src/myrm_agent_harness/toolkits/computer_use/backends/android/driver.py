"""Android ADB Backend implementation conforming to ComputerBackend protocol.

[INPUT]
- types::ActionResult, ScreenInfo, PermissionStatus (POS: shared contracts)

[OUTPUT]
- AndroidAdbBackend: High-level driver coordinating screencap compression, UI pruning, and gestures.

[POS]
Platform backend adapter for Android mobile devices.
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    ModifierKey,
    PermissionStatus,
    ScreenContext,
    ScreenInfo,
    WindowTextResult,
)
from .client import AndroidAdbClient, DeviceConnectionState
from .clipboard import inject_text_utf8
from .compressor import compress_screencap_bytes
from .tree_pruner import AndroidUiPruner, MobileNode

logger = logging.getLogger(__name__)


class AndroidAdbBackend:
    """Full-featured Android device backend over Wireless/USB ADB."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5555) -> None:
        self.client = AndroidAdbClient(host=host, port=port)
        self._last_nodes: list[MobileNode] = []
        self._state: DeviceConnectionState | None = None

    async def connect(self) -> tuple[bool, str]:
        """Establish ADB connection and probe resolution."""
        ok, msg = await self.client.connect()
        if ok:
            self._state = await self.client.probe()
        return ok, msg

    async def pair(self, pairing_port: int, pairing_code: str) -> tuple[bool, str]:
        """Pair with Android 11+ wireless debugging."""
        return await self.client.pair(pairing_port, pairing_code)

    async def screenshot(self, format: str = "WEBP", max_dimension: int = 1280) -> bytes:
        """Capture and compress screenshot from device."""
        raw_png = await self.client.raw_screencap()
        return compress_screencap_bytes(raw_png, max_dimension=max_dimension, output_format=format)

    async def ui_snapshot(self) -> tuple[list[MobileNode], str]:
        """Capture and prune UIAutomator tree into interactive nodes & Markdown summary."""
        xml_dump = await self.client.dump_ui_hierarchy()
        nodes = AndroidUiPruner.extract_interactive_nodes(xml_dump)
        self._last_nodes = nodes
        summary = AndroidUiPruner.to_markdown_summary(nodes)
        return nodes, summary

    async def tap(self, x: int, y: int) -> ActionResult:
        """Tap at screen coordinates."""
        code, out, err = await self.client.run_adb("shell", "input", "tap", str(x), str(y))
        success = code == 0
        return ActionResult(
            success=success,
            message=f"Tapped at ({x}, {y})" if success else f"Tap failed: {out} {err}",
        )

    async def tap_node(self, node_index: int) -> ActionResult:
        """Tap a semantic @m{index} node from the last UI snapshot."""
        for node in self._last_nodes:
            if node.index == node_index:
                return await self.tap(node.center[0], node.center[1])
        return ActionResult(success=False, message=f"Mobile node @m{node_index} not found.")

    async def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300) -> ActionResult:
        """Swipe / scroll gesture from start to end coordinates."""
        code, out, err = await self.client.run_adb(
            "shell", "input", "swipe", str(start_x), str(start_y), str(end_x), str(end_y), str(duration_ms)
        )
        success = code == 0
        return ActionResult(
            success=success,
            message=f"Swiped ({start_x}, {start_y}) -> ({end_x}, {end_y})" if success else f"Swipe failed: {out} {err}",
        )

    async def type_text(self, text: str, delay_ms: int = 12, chunk_size: int = 50) -> ActionResult:
        """Inject multilingual text into the active mobile input field."""
        ok, msg = await inject_text_utf8(self.client, text)
        return ActionResult(success=ok, message=msg)

    async def key(self, key_name: str) -> ActionResult:
        """Press an Android key event (Back, Home, Enter, Power, etc.)."""
        key_map = {
            "back": "KEYCODE_BACK",
            "home": "KEYCODE_HOME",
            "menu": "KEYCODE_APP_SWITCH",
            "enter": "KEYCODE_ENTER",
            "return": "KEYCODE_ENTER",
            "power": "KEYCODE_POWER",
            "volume_up": "KEYCODE_VOLUME_UP",
            "volume_down": "KEYCODE_VOLUME_DOWN",
        }
        android_key = key_map.get(key_name.lower(), key_name.upper())
        code, out, err = await self.client.run_adb("shell", "input", "keyevent", android_key)
        success = code == 0
        return ActionResult(
            success=success,
            message=f"Triggered key {android_key}" if success else f"Keyevent failed: {out} {err}",
        )

    async def launch_app(self, app_alias_or_package: str) -> ActionResult:
        """Launch an app by package name or common alias (e.g. 'wechat', 'dingtalk', 'settings')."""
        known_aliases = {
            "wechat": "com.tencent.mm/.ui.LauncherUI",
            "weixin": "com.tencent.mm/.ui.LauncherUI",
            "dingtalk": "com.alibaba.android.rimet/.biz.LaunchHomeActivity",
            "settings": "com.android.settings/.Settings",
            "chrome": "com.android.chrome/com.google.android.apps.chrome.Main",
            "browser": "com.android.browser/.BrowserActivity",
        }
        target = known_aliases.get(app_alias_or_package.lower(), app_alias_or_package)
        if "/" in target:
            code, out, err = await self.client.run_adb("shell", "am", "start", "-n", target)
        else:
            code, out, err = await self.client.run_adb("shell", "monkey", "-p", target, "-c", "android.intent.category.LAUNCHER", "1")

        success = code == 0
        return ActionResult(
            success=success,
            message=f"Launched {app_alias_or_package} ({target})" if success else f"Launch failed: {out} {err}",
        )

    def screen_info(self) -> ScreenInfo:
        """Return screen dimensions and density."""
        if self._state:
            return ScreenInfo(
                width=self._state.display_width,
                height=self._state.display_height,
                dpi_scale=self._state.density_dpi / 160.0,
            )
        return ScreenInfo(width=1080, height=2400, dpi_scale=2.625)

    def screen_context(self) -> ScreenContext:
        """Return current mobile context."""
        return ScreenContext(
            active_window=self._state.model if self._state else "Android Phone",
            mouse_x=0,
            mouse_y=0,
        )

    async def window_text(self) -> WindowTextResult:
        """Extract text from current mobile screen."""
        _, summary = await self.ui_snapshot()
        return WindowTextResult(
            text=summary,
            success=True,
            fallback_used=False,
            window_title=self._state.model if self._state else "Android",
        )

    async def check_permissions(self, *, probe_capture: bool = False) -> PermissionStatus:
        """Check wireless ADB connection readiness."""
        connected = self.client._connected
        return PermissionStatus(
            accessibility=connected,
            screen_recording=connected,
            all_granted=connected,
            capture_ready=connected,
            screen_recording_capturable=connected if probe_capture else None,
            settings_deeplinks=[],
        )

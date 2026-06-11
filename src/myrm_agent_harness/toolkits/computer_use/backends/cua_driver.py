"""cua-driver backend — background input via MCP stdio.

Wraps a platform fallback backend (MacOS/Windows) and delegates **input**
operations (click, type, key, scroll, drag, mouse_move) to `cua-driver`
via its MCP stdio transport.  Non-input operations (screenshot, screen_info,
window_text, etc.) are forwarded to the platform-native backend unchanged.

cua-driver uses private OS APIs (macOS SkyLight SPIs, Windows Touch Injection)
to simulate user input *without* stealing focus or moving the cursor —
enabling truly background desktop automation.

Install: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh)"`

License: MIT (https://github.com/trycua/cua)

[INPUT]
- protocols::ComputerBackend (POS: fallback platform backend)
- types::ActionResult, ModifierKey, ScreenInfo, ScreenContext, WindowTextResult, PermissionStatus (POS: shared types)

[OUTPUT]
- CuaDriverBackend: ComputerBackend implementation with background input
- is_cua_driver_available: availability probe

[POS]
Optional enhancement backend. Only loaded when cua-driver is installed.
All operations gracefully degrade to platform-native backends when unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from contextlib import AsyncExitStack
from typing import Any

from myrm_agent_harness.toolkits.computer_use.backends.protocols import ComputerBackend
from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    ModifierKey,
    PermissionStatus,
    ScreenContext,
    ScreenInfo,
    WindowTextResult,
)

logger = logging.getLogger(__name__)

_CUA_DRIVER_CMD = os.environ.get("MYRM_CUA_DRIVER_CMD", "cua-driver")

_MODIFIER_TO_CUA: dict[ModifierKey, str] = {
    "ctrl": "ctrl",
    "shift": "shift",
    "alt": "option",
    "meta": "cmd",
}

_WINDOW_LINE_RE = re.compile(
    r"^-\s+(.+?)\s+\(pid\s+(\d+)\)\s+.*\[window_id:\s+(\d+)\]",
    re.MULTILINE,
)


def is_cua_driver_available() -> bool:
    """Return True if ``cua-driver`` binary is on ``$PATH``."""
    return bool(shutil.which(_CUA_DRIVER_CMD))


def cua_driver_install_hint() -> str:
    return (
        "cua-driver is not installed. Install:\n"
        '  /bin/bash -c "$(curl -fsSL '
        'https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh)"'
    )


class _McpSession:
    """Manages a persistent MCP stdio session to cua-driver."""

    def __init__(self) -> None:
        self._session: Any = None
        self._exit_stack: AsyncExitStack | None = None
        self._started = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            await self._connect()
            self._started = True

    async def _connect(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        stack = AsyncExitStack()
        params = StdioServerParameters(
            command=_CUA_DRIVER_CMD,
            args=["mcp"],
            env={**os.environ},
        )
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._exit_stack = stack
        self._session = session

    async def stop(self) -> None:
        async with self._lock:
            if self._exit_stack is not None:
                try:
                    await self._exit_stack.aclose()
                except Exception as exc:
                    logger.warning("cua-driver shutdown error: %s", exc)
            self._exit_stack = None
            self._session = None
            self._started = False

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call a cua-driver MCP tool.  Auto-reconnects once on transport errors."""
        if not self._started:
            raise RuntimeError("cua-driver session not started")
        try:
            return await self._do_call(name, args)
        except Exception as exc:
            if not self._is_transport_error(exc):
                raise
            logger.warning("cua-driver transport closed during %s; reconnecting", name)
            async with self._lock:
                await self._reconnect()
            return await self._do_call(name, args)

    async def _do_call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = await self._session.call_tool(name, args)
        return _extract_result(result)

    async def _reconnect(self) -> None:
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
        self._started = False
        await self._connect()
        self._started = True

    @staticmethod
    def _is_transport_error(exc: Exception) -> bool:
        name = type(exc).__name__
        return name in {"ClosedResourceError", "BrokenResourceError", "EndOfStream"} or isinstance(
            exc, (BrokenPipeError, EOFError)
        )


def _extract_result(mcp_result: Any) -> dict[str, Any]:
    """Flatten an MCP CallToolResult into a plain dict."""
    is_error = bool(getattr(mcp_result, "isError", False))
    text_chunks: list[str] = []
    images: list[str] = []
    for part in getattr(mcp_result, "content", []) or []:
        ptype = getattr(part, "type", None)
        if ptype == "text":
            text_chunks.append(getattr(part, "text", "") or "")
        elif ptype == "image":
            b64 = getattr(part, "data", None)
            if b64:
                images.append(b64)
    data: Any = "\n".join(text_chunks) if text_chunks else None
    structured = getattr(mcp_result, "structuredContent", None)
    return {"data": data, "images": images, "structuredContent": structured, "isError": is_error}


class CuaDriverBackend:
    """Background-input backend using cua-driver MCP over stdio.

    Delegates **input** actions (click, type, key, scroll, drag, mouse_move) to
    cua-driver for focus-free operation.  Non-input operations (screenshot,
    screen_info, window_text, etc.) are forwarded to the platform-native
    ``fallback`` backend.
    """

    def __init__(self, fallback: ComputerBackend) -> None:
        self._fallback = fallback
        self._mcp = _McpSession()
        self._active_pid: int | None = None
        self._active_window_id: int | None = None

    async def _ensure_session(self) -> None:
        if not self._mcp._started:
            await self._mcp.start()

    async def _resolve_target(self) -> int:
        """Ensure we have a valid target PID (frontmost on-screen window)."""
        if self._active_pid is not None:
            return self._active_pid

        out = await self._mcp.call_tool("list_windows", {"on_screen_only": True})
        sc = out.get("structuredContent") or {}
        raw_windows = sc.get("windows") if sc else None

        if raw_windows:
            windows = sorted(raw_windows, key=lambda w: w.get("z_index", 0))
        else:
            raw_text = out["data"] if isinstance(out["data"], str) else ""
            windows = [
                {"app_name": m.group(1), "pid": int(m.group(2)), "window_id": int(m.group(3))}
                for m in _WINDOW_LINE_RE.finditer(raw_text)
            ]

        on_screen = [w for w in windows if w.get("is_on_screen", True) and not w.get("off_screen", False)]
        target = on_screen[0] if on_screen else (windows[0] if windows else None)
        if not target:
            raise RuntimeError("cua-driver: no on-screen window found")

        self._active_pid = int(target["pid"])
        self._active_window_id = int(target.get("window_id", 0))
        return self._active_pid

    def _invalidate_target(self) -> None:
        """Reset cached PID so the next action re-resolves the frontmost window."""
        self._active_pid = None
        self._active_window_id = None

    # ── Delegated to fallback (non-input, no focus concern) ──────

    async def screenshot(self) -> bytes:
        return await self._fallback.screenshot()

    def screen_info(self) -> ScreenInfo:
        return self._fallback.screen_info()

    def screen_context(self) -> ScreenContext:
        return self._fallback.screen_context()

    async def window_text(self) -> WindowTextResult:
        return await self._fallback.window_text()

    async def has_blocking_dialog(self, target_app_names: list[str] | None = None) -> bool:
        return await self._fallback.has_blocking_dialog(target_app_names)

    async def is_browser_active(self) -> bool:
        return await self._fallback.is_browser_active()

    async def check_permissions(self) -> PermissionStatus:
        return await self._fallback.check_permissions()

    async def wait(self, seconds: float) -> ActionResult:
        return await self._fallback.wait(seconds)

    # ── Background input via cua-driver ──────────────────────────

    async def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        try:
            await self._ensure_session()
            pid = await self._resolve_target()

            tool = "right_click" if button == "right" else ("double_click" if clicks >= 2 else "click")
            args: dict[str, Any] = {"pid": pid, "x": x, "y": y}
            if modifiers:
                args["modifier"] = [_MODIFIER_TO_CUA[m] for m in modifiers]

            out = await self._mcp.call_tool(tool, args)
            if out["isError"]:
                raise RuntimeError(out.get("data", "cua-driver click failed"))
            return ActionResult(success=True)
        except Exception as exc:
            logger.warning("cua-driver click failed, falling back to pyautogui: %s", exc)
            return await self._fallback.click(x, y, button, clicks, modifiers=modifiers)

    async def type_text(self, text: str, delay_ms: int = 12, chunk_size: int = 50) -> ActionResult:
        try:
            await self._ensure_session()
            pid = await self._resolve_target()
            out = await self._mcp.call_tool("type_text", {"pid": pid, "text": text})
            if out["isError"]:
                raise RuntimeError(out.get("data", "cua-driver type_text failed"))
            return ActionResult(success=True)
        except Exception as exc:
            logger.warning("cua-driver type_text failed, falling back: %s", exc)
            return await self._fallback.type_text(text, delay_ms, chunk_size)

    async def type_credential(self, label: str) -> ActionResult:
        """Credential typing: retrieve from vault, then type via cua-driver."""
        from myrm_agent_harness.toolkits.security.credential_vault import get_global_credential_vault

        vault = get_global_credential_vault()
        is_totp = label.endswith("-totp")
        try:
            secret_text = vault.get_totp_token(label) if is_totp else vault.get_password(label)
        except Exception as exc:
            return ActionResult(success=False, error=f"Failed to retrieve credential '{label}': {exc}")

        try:
            await self._ensure_session()
            pid = await self._resolve_target()
            out = await self._mcp.call_tool("type_text", {"pid": pid, "text": secret_text})
            if out["isError"]:
                raise RuntimeError(out.get("data", "cua-driver type_credential failed"))
            return ActionResult(success=True)
        except Exception as exc:
            logger.warning("cua-driver type_credential failed, falling back: %s", exc)
            return await self._fallback.type_credential(label)

    async def key(self, keys: str) -> ActionResult:
        try:
            await self._ensure_session()
            pid = await self._resolve_target()

            parts = [k.strip().lower() for k in re.split(r"[+\-]", keys) if k.strip()]
            modifier_names = {"cmd", "command", "shift", "option", "alt", "ctrl", "control", "fn"}
            key_aliases = {"command": "cmd", "alt": "option", "control": "ctrl", "meta": "cmd"}

            mods: list[str] = []
            key_name: str | None = None
            for part in parts:
                normalized = key_aliases.get(part, part)
                if normalized in modifier_names:
                    mods.append(normalized)
                else:
                    key_name = part

            if key_name and mods:
                out = await self._mcp.call_tool("hotkey", {"pid": pid, "keys": mods + [key_name]})
            elif key_name:
                out = await self._mcp.call_tool("press_key", {"pid": pid, "key": key_name})
            else:
                raise ValueError(f"Could not parse key from '{keys}'")

            if out["isError"]:
                raise RuntimeError(out.get("data", "cua-driver key failed"))
            return ActionResult(success=True)
        except Exception as exc:
            logger.warning("cua-driver key failed, falling back: %s", exc)
            return await self._fallback.key(keys)

    async def mouse_move(self, x: int, y: int) -> ActionResult:
        try:
            await self._ensure_session()
            pid = await self._resolve_target()
            out = await self._mcp.call_tool("mouse_move", {"pid": pid, "x": x, "y": y})
            if out["isError"]:
                raise RuntimeError(out.get("data", "cua-driver mouse_move failed"))
            return ActionResult(success=True)
        except Exception as exc:
            logger.warning("cua-driver mouse_move failed, falling back: %s", exc)
            return await self._fallback.mouse_move(x, y)

    async def scroll(
        self,
        x: int,
        y: int,
        direction: str,
        amount: int = 3,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        try:
            await self._ensure_session()
            pid = await self._resolve_target()
            args: dict[str, Any] = {
                "pid": pid,
                "x": x,
                "y": y,
                "direction": direction,
                "amount": max(1, min(50, amount)),
            }
            out = await self._mcp.call_tool("scroll", args)
            if out["isError"]:
                raise RuntimeError(out.get("data", "cua-driver scroll failed"))
            return ActionResult(success=True)
        except Exception as exc:
            logger.warning("cua-driver scroll failed, falling back: %s", exc)
            return await self._fallback.scroll(x, y, direction, amount, modifiers=modifiers)

    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        try:
            await self._ensure_session()
            pid = await self._resolve_target()
            args: dict[str, Any] = {
                "pid": pid,
                "from_x": start_x,
                "from_y": start_y,
                "to_x": end_x,
                "to_y": end_y,
            }
            out = await self._mcp.call_tool("drag", args)
            if out["isError"]:
                raise RuntimeError(out.get("data", "cua-driver drag failed"))
            return ActionResult(success=True)
        except Exception as exc:
            logger.warning("cua-driver drag failed, falling back: %s", exc)
            return await self._fallback.drag(start_x, start_y, end_x, end_y, modifiers=modifiers)

    async def close(self) -> None:
        """Shut down the cua-driver MCP session."""
        await self._mcp.stop()

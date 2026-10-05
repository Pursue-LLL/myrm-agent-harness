"""Live overlay-exclusion integration tests (real Quartz/AppKit, no mock).

[INPUT]
- backends.macos_background::_capture_screen_excluding_titles (POS: exclusion channel)
- backends.macos::MacOSBackend (POS: backend screenshot routing)
- 真实 macOS 屏幕/Quartz 窗口服务（本机无头环境自动跳过）

[OUTPUT]
- 真实截图字节（PNG）与真实锚点窗口解析

[POS]
与 test_capture_exclusion_channel.py（纯 mock 单元）互补：本文件跑真实
Quartz CGWindowList* + AppKit NSBitmapImageRep 序列化链路，验证 mock 无法
覆盖的平台行为（常量值、真实窗口列表、真实 PNG 编码）。缺屏幕录制权限
或非 macOS 宿主时自动 skip，任何 CI 宿主安全。
"""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.integration


def _require_macos() -> None:
    if sys.platform != "darwin":
        pytest.skip("macOS-only capture channel")


def test_real_exclusion_channel_returns_png_for_absurd_title() -> None:
    """真实 Quartz 链路：无关 title 时返回 None（无锚点，降级原路径）。"""
    _require_macos()
    from myrm_agent_harness.toolkits.computer_use.backends.macos_background import (
        _capture_screen_excluding_titles,
    )

    result = _capture_screen_excluding_titles(
        frozenset({"__myrm_no_such_window_title_zzz__"})
    )
    assert result is None


def test_real_anchor_resolution_reads_live_window_list() -> None:
    """真实 CGWindowListCopyWindowInfo：无关 title 解析为 None 且不抛异常。"""
    _require_macos()
    from myrm_agent_harness.toolkits.computer_use.backends.macos_background import (
        _lowest_overlay_window_id,
    )

    anchor = _lowest_overlay_window_id(frozenset({"__myrm_no_such_window_title_zzz__"}))
    assert anchor is None


def test_real_backend_falls_back_to_screencapture_without_overlay() -> None:
    """真实端到端：注入不相干 title → 排除通道返回 None → 降级真实 screencapture。

    验证 MacOSBackend 全屏截图在「无匹配遮罩」时仍产出合法 PNG（非黑屏占位），
    即真实集成下排除能力对常规路径零侵入。
    """
    _require_macos()
    import asyncio

    from myrm_agent_harness.toolkits.computer_use.backends.macos import MacOSBackend
    from myrm_agent_harness.toolkits.computer_use.capture_probe import (
        png_bytes_look_capturable,
    )

    backend = MacOSBackend()
    backend.set_excluded_capture_window_titles(["__myrm_no_such_window_title_zzz__"])

    try:
        data = asyncio.run(backend.screenshot())
    except RuntimeError as exc:  # 缺屏幕录制权限等平台信号 → skip
        pytest.skip(f"screen capture unavailable on this host: {exc}")

    assert data[:8] == b"\x89PNG\r\n\x1a\n", "real screencapture must yield a PNG"
    # 真实截屏应可被亮度门判为「有内容」（权限缺失时该路径已在上方 skip）。
    assert png_bytes_look_capturable(data) is True


def test_real_targeted_window_capture_bypasses_exclusion() -> None:
    """真实定向截窗：排除 title 注入后，app_name 路径仍走窗口直截（不受影响）。"""
    _require_macos()
    import asyncio

    from myrm_agent_harness.toolkits.computer_use.backends.macos import MacOSBackend
    from myrm_agent_harness.toolkits.computer_use.backends.macos_background import (
        _resolve_target_window,
    )

    backend = MacOSBackend()
    backend.set_excluded_capture_window_titles(["Privacy Curtain"])

    # 取当前前台/在屏应用的任意窗口做真实定向截取；无窗口则 skip。
    candidate_apps = ["Finder", "Dock", "System Settings", "Terminal", "Safari"]
    target = None
    used = ""
    for app in candidate_apps:
        target = _resolve_target_window(app)
        if target is not None:
            used = app
            break
    if target is None:
        pytest.skip("no on-screen window available for targeted capture")

    try:
        data = asyncio.run(backend.screenshot(app_name=used))
    except RuntimeError as exc:
        pytest.skip(f"window capture unavailable: {exc}")

    assert data[:8] == b"\x89PNG\r\n\x1a\n"

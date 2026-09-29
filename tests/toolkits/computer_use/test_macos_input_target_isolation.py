"""macOS 后台输入目标的并发隔离。

复现场景：同进程两个 desktop 后台任务交错执行 healer bbox 路径 —
任务 A set_target 后在 await 点让出，任务 B 完整执行一次 set/post/clear，
任务 A 恢复后继续投递。若路由状态是进程全局，A 的后续事件会误投
（B clear 后回落全局 HID，直击前台窗口）；修复后 A 全程直投自己的 pid。
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.computer_use.backends import macos_input as macos_input_mod


@pytest.fixture()
def quartz_stub(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a stub Quartz module so macOS imports work on Linux."""
    stub = MagicMock(name="Quartz")
    stub.kCGHIDEventTap = 0
    monkeypatch.setitem(sys.modules, "Quartz", stub)
    return stub


async def test_interleaved_targets_stay_isolated(
    quartz_stub: MagicMock,
) -> None:
    macos_input_mod.clear_input_target()
    quartz_stub.reset_mock()
    a_set = asyncio.Event()
    b_finished = asyncio.Event()

    async def worker_a() -> None:
        macos_input_mod.set_input_target(111)
        a_set.set()
        # 模拟 healer await _run_bbox_action（多次 to_thread 让出）期间被抢占。
        await b_finished.wait()
        macos_input_mod._post_event(object())
        macos_input_mod.clear_input_target()

    async def worker_b() -> None:
        await a_set.wait()
        macos_input_mod.set_input_target(222)
        try:
            macos_input_mod._post_event(object())
        finally:
            macos_input_mod.clear_input_target()
        b_finished.set()

    await asyncio.gather(worker_a(), worker_b())

    pid_calls = [c[0][0] for c in quartz_stub.CGEventPostToPid.call_args_list]
    # B 一次直投 222；A 在 B 完整执行后仍直投 111（全局实现下 A 会走 HID）。
    assert pid_calls == [222, 111], f"target pid leaked across tasks: {pid_calls}"
    quartz_stub.CGEventPost.assert_not_called()

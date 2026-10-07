"""单元测试：持久化交互式脚本桌面执行会话与多步原子批处理套件 (Item 204).

[INPUT]
- PersistentDesktopReplEngine
- ReplScriptCommand
- ReplRuntimeKind
- ReplExecutionStatus
- DesktopReplSessionSnapshot

[OUTPUT]
- 验证跨回合在会话沙箱中保持变量生命周期与对象引用
- 验证内置 Desktop SDK 多步原子自动化批处理执行（避免多轮往返）
- 验证 repl_reset 毫秒级环境原子复位与脏状态清理
- 验证执行异常捕获、会话状态快照审计与生命周期销毁
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.desktop_repl import (
    DesktopApiSdk,
    DesktopReplSessionSnapshot,
    PersistentDesktopReplEngine,
    ReplExecutionResult,
    ReplExecutionStatus,
    ReplRuntimeKind,
    ReplScriptCommand,
)


def test_cross_turn_state_retention() -> None:
    """验证跨回合持久化：前一回合声明的变量与对象在后续回合中无缝复用。"""
    engine = PersistentDesktopReplEngine()
    session_id = "test_desktop_session_01"

    # Turn 1: 声明列表与基础变量
    cmd1 = ReplScriptCommand(
        code="data_list = [10, 20]\nprefix = 'TASK_DONE'",
        runtime=ReplRuntimeKind.PYTHON_REPL,
    )
    res1 = engine.execute_script(session_id, cmd1)
    assert res1.is_success()
    assert "data_list" in res1.persisted_variables
    assert "prefix" in res1.persisted_variables

    # Turn 2: 依赖前一回合的变量进行就地追加与修改
    cmd2 = ReplScriptCommand(
        code="data_list.append(30)\nresult_str = f'{prefix}_{sum(data_list)}'",
        runtime=ReplRuntimeKind.PYTHON_REPL,
    )
    res2 = engine.execute_script(session_id, cmd2)
    assert res2.is_success()
    assert "result_str" in res2.persisted_variables

    # Turn 3: 打印并验证最终计算结果
    cmd3 = ReplScriptCommand(
        code="print(result_str)",
        runtime=ReplRuntimeKind.PYTHON_REPL,
    )
    res3 = engine.execute_script(session_id, cmd3)
    assert res3.is_success()
    assert "TASK_DONE_60" in res3.stdout


def test_multistep_atomic_batch_desktop_automation() -> None:
    """验证多步自动化小脚本在 REPL 内部一次性原子批处理执行，极大削减 LLM API 往返。"""
    engine = PersistentDesktopReplEngine()
    session_id = "test_desktop_session_batch"

    script = """
elem = desktop.find_element('#submit-btn')
elem.click()
desktop.type_text('#search-box', 'open-perplexity')
desktop.click('#search-btn')
print('Batch automation complete.')
"""
    cmd = ReplScriptCommand(code=script)
    res = engine.execute_script(session_id, cmd)

    assert res.is_success()
    assert "Batch automation complete." in res.stdout
    assert "elem" in res.persisted_variables

    # 验证底层 Desktop SDK 记录的动作流水账
    ns = engine.get_or_create_namespace(session_id)
    desktop_obj = ns.get("desktop")
    assert isinstance(desktop_obj, DesktopApiSdk)
    actions = desktop_obj.get_actions()
    assert "find:#submit-btn" in actions
    assert "type:#search-box:open-perplexity" in actions
    assert "click:#search-btn" in actions


def test_repl_reset_atomic_wipe() -> None:
    """验证 repl_reset 毫秒级复位：彻底清除污染变量并恢复干净初始环境。"""
    engine = PersistentDesktopReplEngine()
    session_id = "test_desktop_session_reset"

    # 先声明大量脏变量
    cmd = ReplScriptCommand(code="x = 100\ny = 'dirty'\nflag = True")
    res = engine.execute_script(session_id, cmd)
    assert len(res.persisted_variables) == 3

    # 执行 repl_reset
    reset_res = engine.repl_reset(session_id)
    assert reset_res.status == ReplExecutionStatus.RESET_TRIGGERED
    assert reset_res.was_reset is True
    assert reset_res.persisted_variables == []

    # 验证重置后旧变量不可访问
    verify_cmd = ReplScriptCommand(code="print(x)")
    verify_res = engine.execute_script(session_id, verify_cmd)
    assert verify_res.status == ReplExecutionStatus.ERROR
    assert "name 'x' is not defined" in verify_res.stderr


def test_execution_error_capture_and_session_snapshot() -> None:
    """验证语法/运行时异常安全捕获、会话状态快照与生命周期关闭。"""
    engine = PersistentDesktopReplEngine()
    session_id = "test_desktop_session_audit"

    # 1. 执行引发 ZeroDivisionError 的代码
    bad_cmd = ReplScriptCommand(code="val = 10 / 0")
    bad_res = engine.execute_script(session_id, bad_cmd)
    assert bad_res.status == ReplExecutionStatus.ERROR
    assert "[ExecutionError]: division by zero" in bad_res.stderr

    # 2. 正常执行并获取快照
    good_cmd = ReplScriptCommand(code="score: int = 99\nlabel: str = 'Pass'")
    good_res = engine.execute_script(session_id, good_cmd)
    assert good_res.is_success()

    snapshot: DesktopReplSessionSnapshot = engine.get_snapshot(session_id)
    assert snapshot.is_alive is True
    assert snapshot.execution_count == 2
    assert "score" in snapshot.variable_names
    assert snapshot.variable_types.get("score") == "int"
    assert snapshot.variable_types.get("label") == "str"

    out_dict = snapshot.to_dict()
    assert out_dict["session_id"] == session_id
    assert out_dict["execution_count"] == 2

    # 3. 关闭会话
    engine.close_session(session_id)
    dead_snapshot = engine.get_snapshot(session_id)
    assert dead_snapshot.is_alive is False

"""单元测试：会话级隐私模式：卸除全部工具硬门禁套件 (Item 194)。

覆盖测试点：
1. 常规模式与仅无痕模式下的工具全量暴露与记忆写入权限区分
2. 严格隐私模式 (TOOLS_OFF_STRICT) 工具全量收走硬隔离
3. 模型擅自返回 tool_call 时执行层硬拒绝拦截与安全提示注入
4. 双重严格模式 (TOOLS_OFF_AND_INCOGNITO) 工具全关且记忆全禁
5. 擅自工具调用审计账本追溯与清空维护
"""

from myrm_agent_harness.agent.context_management.privacy_mode import (
    ConversationPrivacyGateEngine,
    PrivacyBoundToolSet,
    PrivacyModeLevel,
    PrivacyModeSessionConfig,
    ToolCallInterceptRecord,
    ToolHardGateAction,
)


def test_bind_tools_standard_vs_incognito() -> None:
    """测试常规模式与仅无痕模式下工具暴露与记忆写入行为。"""
    engine = ConversationPrivacyGateEngine()
    tools = ("bash_run", "read_file", "write_file", "search_web", "memory_store")

    # 1. 常规模式：工具全开，记忆可写
    cfg_std = PrivacyModeSessionConfig(privacy_level=PrivacyModeLevel.STANDARD)
    bound_std = engine.bind_tools_for_session(tools, cfg_std)
    assert bound_std.is_tools_off is False
    assert len(bound_std.exposed_tool_names) == 5
    assert engine.is_memory_write_permitted(cfg_std) is True

    # 2. 仅无痕模式：工具全开，但记忆禁止写入
    cfg_inc = PrivacyModeSessionConfig(privacy_level=PrivacyModeLevel.INCOGNITO_ONLY)
    bound_inc = engine.bind_tools_for_session(tools, cfg_inc)
    assert bound_inc.is_tools_off is False
    assert len(bound_inc.exposed_tool_names) == 5
    assert engine.is_memory_write_permitted(cfg_inc) is False


def test_bind_tools_strict_tools_off() -> None:
    """测试严格隐私模式下工具全部收走硬隔离。"""
    engine = ConversationPrivacyGateEngine()
    tools = ("bash_run", "read_file", "write_file", "search_web")

    # 1. 默认无白名单：收走全部工具
    cfg_strict = PrivacyModeSessionConfig(
        privacy_level=PrivacyModeLevel.TOOLS_OFF_STRICT
    )
    bound_strict = engine.bind_tools_for_session(tools, cfg_strict)
    assert bound_strict.is_tools_off is True
    assert len(bound_strict.exposed_tool_names) == 0
    assert bound_strict.original_tool_count == 4

    # 2. 携带受控系统元工具白名单：仅暴露白名单元工具
    cfg_meta = PrivacyModeSessionConfig(
        privacy_level=PrivacyModeLevel.TOOLS_OFF_STRICT,
        allowed_system_meta_tools=("read_file",),
    )
    bound_meta = engine.bind_tools_for_session(tools, cfg_meta)
    assert bound_meta.is_tools_off is True
    assert bound_meta.exposed_tool_names == ("read_file",)


def test_intercept_hard_denied_tool_call() -> None:
    """测试模型擅自返回 tool_call 时执行层硬拒绝拦截。"""
    engine = ConversationPrivacyGateEngine()
    cfg_strict = PrivacyModeSessionConfig(
        privacy_level=PrivacyModeLevel.TOOLS_OFF_STRICT
    )
    sid = "sess_confidential_legal_review"

    # 模拟模型擅自尝试调用 bash_run 执行系统命令
    blocked, record, notice = engine.intercept_and_hard_gate_tool_call(
        tool_name="bash_run",
        tool_args="cat /etc/passwd",
        session_config=cfg_strict,
        session_id=sid,
        tool_call_id="call_unauthorized_001",
    )

    assert blocked is True
    assert record.gate_action == ToolHardGateAction.HARD_DENIED_TOOLS_OFF
    assert record.tool_name == "bash_run"
    assert record.tool_call_id == "call_unauthorized_001"
    assert "PRIVACY_MODE_HARD_GATE" in notice
    assert "rejected by the security layer" in notice
    assert "bash_run" in notice

    # 常规模式下相同调用应正常允许
    cfg_std = PrivacyModeSessionConfig(privacy_level=PrivacyModeLevel.STANDARD)
    blocked_std, record_std, notice_std = engine.intercept_and_hard_gate_tool_call(
        tool_name="bash_run",
        tool_args="ls -la",
        session_config=cfg_std,
        session_id=sid,
    )
    assert blocked_std is False
    assert record_std.gate_action == ToolHardGateAction.PERMITTED
    assert notice_std == ""


def test_dual_tools_off_and_incognito_mode() -> None:
    """测试双重严格模式 (TOOLS_OFF_AND_INCOGNITO) 最高安全等级。"""
    engine = ConversationPrivacyGateEngine()
    cfg_dual = PrivacyModeSessionConfig(
        privacy_level=PrivacyModeLevel.TOOLS_OFF_AND_INCOGNITO
    )

    # 工具全关
    bound = engine.bind_tools_for_session(("tool_a", "tool_b"), cfg_dual)
    assert bound.is_tools_off is True
    assert len(bound.exposed_tool_names) == 0

    # 记忆全禁
    assert engine.is_memory_write_permitted(cfg_dual) is False

    # 擅自调用硬拒绝
    blocked, record, _ = engine.intercept_and_hard_gate_tool_call(
        tool_name="tool_a",
        tool_args="{}",
        session_config=cfg_dual,
    )
    assert blocked is True
    assert record.gate_action == ToolHardGateAction.HARD_DENIED_TOOLS_OFF


def test_intercept_history_and_clear() -> None:
    """测试擅自调用拦截历史账本审计与清空。"""
    engine = ConversationPrivacyGateEngine()
    cfg = PrivacyModeSessionConfig(privacy_level=PrivacyModeLevel.TOOLS_OFF_STRICT)
    sid = "sess_audit_test"

    engine.intercept_and_hard_gate_tool_call("mcp_external", "{}", cfg, session_id=sid)
    engine.intercept_and_hard_gate_tool_call("vault_read", "{}", cfg, session_id=sid)

    history = engine.get_intercept_history(sid)
    assert len(history) == 2
    assert history[0].tool_name == "mcp_external"
    assert history[1].tool_name == "vault_read"

    engine.clear_intercept_history(sid)
    assert len(engine.get_intercept_history(sid)) == 0

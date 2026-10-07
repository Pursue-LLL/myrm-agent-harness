"""显式工作区探索守卫与自主扫盘抑制套件单元测试。

[INPUT]
- WorkspaceExplorationGuardEngine, WorkspaceAccessPolicy, ExplorationDecisionStatus, WorkspaceGuardConfig

[OUTPUT]
- 自动化验证三态策略裁决、提示词对抗性扫盘抑制、显式引用免阻断与超深度递归拦截

[POS]
- 位于 tests/agent/context_management/test_workspace_guard_engine.py
"""

from myrm_agent_harness.agent.context_management.workspace_guard import (
    ExplorationDecisionStatus,
    ExplorationGuardDecision,
    WorkspaceAccessPolicy,
    WorkspaceExplorationGuardEngine,
    WorkspaceGuardConfig,
)


def test_non_exploration_tool_always_allowed() -> None:
    """测试非目录探索类工具（如代码执行或文件读取）始终直接放行。"""
    engine = WorkspaceExplorationGuardEngine()

    decision: ExplorationGuardDecision = engine.evaluate_tool_exploration(
        tool_name="read_file",
        tool_args={"path": "src/main.py"},
        user_prompt="请帮我检查代码语法",
        session_policy=WorkspaceAccessPolicy.EXPLICIT_ONLY,
    )

    assert decision.allowed is True
    assert decision.status == ExplorationDecisionStatus.ALLOWED
    assert decision.suppression_triggered_by_prompt is False


def test_explicit_only_blocks_unauthorized_exploration() -> None:
    """测试 Explicit-Only 模式下阻断 Agent 未授权的自主搜盘行为。"""
    engine = WorkspaceExplorationGuardEngine()

    decision = engine.evaluate_tool_exploration(
        tool_name="list_dir",
        tool_args={"path": "src/controllers"},
        user_prompt="请解释一下红黑树的旋转算法原理",
        session_policy=WorkspaceAccessPolicy.EXPLICIT_ONLY,
    )

    assert decision.allowed is False
    assert decision.status == ExplorationDecisionStatus.REJECTED_BY_EXPLICIT_RULE
    assert "Explicit-Only" in decision.reason
    assert "用户未显式授权" in decision.feedback_message


def test_explicit_only_allows_explicitly_mentioned_path() -> None:
    """测试 Explicit-Only 模式下，用户显式指名或 @提及的路径放行探索。"""
    engine = WorkspaceExplorationGuardEngine()

    # 1. 显式路径指名
    decision1 = engine.evaluate_tool_exploration(
        tool_name="list_dir",
        tool_args={"path": "myrm-agent-harness/src"},
        user_prompt="请查看 myrm-agent-harness/src 下有哪些模块",
        session_policy=WorkspaceAccessPolicy.EXPLICIT_ONLY,
    )
    assert decision1.allowed is True
    assert decision1.status == ExplorationDecisionStatus.ALLOWED

    # 2. @基名提及
    decision2 = engine.evaluate_tool_exploration(
        tool_name="list_directory",
        tool_args={"path": "workspace/controllers"},
        user_prompt="请核对一下 @controllers 里面的代码文件",
        session_policy=WorkspaceAccessPolicy.EXPLICIT_ONLY,
    )
    assert decision2.allowed is True
    assert decision2.status == ExplorationDecisionStatus.ALLOWED


def test_prompt_crawl_suppression_triggers_override() -> None:
    """测试用户提示词否定指令（如'不要翻看文件夹'）对抗性提升为强制静默阻断。"""
    engine = WorkspaceExplorationGuardEngine()

    # 会话本为全量自动模式 AUTO_INDEX，但用户强调不要看文件夹
    prompt = "不要翻看文件夹，只回答理论：什么是 Paxos 共识算法？"
    decision = engine.evaluate_tool_exploration(
        tool_name="list_dir",
        tool_args={"path": "."},
        user_prompt=prompt,
        session_policy=WorkspaceAccessPolicy.AUTO_INDEX,
    )

    assert decision.allowed is False
    assert decision.status == ExplorationDecisionStatus.REJECTED_BY_PROMPT_SUPPRESSION
    assert decision.effective_policy == WorkspaceAccessPolicy.EXPLICIT_ONLY
    assert decision.suppression_triggered_by_prompt is True
    assert "提示词已明确要求不要检查文件夹" in decision.feedback_message


def test_on_demand_depth_limiting() -> None:
    """测试 On-Demand 模式下浅层放行与超深度递归拦截。"""
    config = WorkspaceGuardConfig(max_on_demand_depth=1)
    engine = WorkspaceExplorationGuardEngine(config)

    # 浅层单层探测 (depth=1) -> 放行
    decision_shallow = engine.evaluate_tool_exploration(
        tool_name="find_files",
        tool_args={"path": "tests", "depth": 1},
        user_prompt="找找单测",
        session_policy=WorkspaceAccessPolicy.ON_DEMAND,
    )
    assert decision_shallow.allowed is True
    assert decision_shallow.status == ExplorationDecisionStatus.ALLOWED

    # 超深跨级递归 (depth=4) -> 拦截
    decision_deep = engine.evaluate_tool_exploration(
        tool_name="find_files",
        tool_args={"path": "tests", "depth": 4},
        user_prompt="找找单测",
        session_policy=WorkspaceAccessPolicy.ON_DEMAND,
    )
    assert decision_deep.allowed is False
    assert decision_deep.status == ExplorationDecisionStatus.REJECTED_DEPTH_EXCEEDED
    assert "探测深度超限" in decision_deep.feedback_message


def test_auto_index_mode_allows_full_exploration() -> None:
    """测试 Auto-Index 模式下无对抗否定词时全量放行。"""
    engine = WorkspaceExplorationGuardEngine()

    decision = engine.evaluate_tool_exploration(
        tool_name="workspace_tree",
        tool_args={"path": "src", "depth": 5},
        user_prompt="请帮我全面梳理工程项目文件树",
        session_policy=WorkspaceAccessPolicy.AUTO_INDEX,
    )

    assert decision.allowed is True
    assert decision.status == ExplorationDecisionStatus.ALLOWED
    assert decision.effective_policy == WorkspaceAccessPolicy.AUTO_INDEX

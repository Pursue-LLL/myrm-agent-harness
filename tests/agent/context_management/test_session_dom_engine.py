"""通用事件溯源会话 DOM、声明式生命周期与真回滚引擎单元测试。

[INPUT]
- SessionDomTree, UniversalEventSourcedSessionDomEngine, SessionDomNodeKind, SessionDomPatchOp, SessionDomPatch, RewindLifecycleWorklist

[OUTPUT]
- 自动化验证 DOM 树节点生命周期、基于 DOM Diff 的绝对真实 Rewind 工作清单推导、后台进程与子 Agent 自动析构清单生成、零状态纯投影提取

[POS]
- 位于 tests/agent/context_management/test_session_dom_engine.py
"""

from myrm_agent_harness.agent.context_management.session_dom import (
    RewindLifecycleAction,
    RewindLifecycleWorklist,
    SessionDomNode,
    SessionDomNodeKind,
    SessionDomPatch,
    SessionDomPatchOp,
    SessionDomTree,
    UniversalEventSourcedSessionDomEngine,
)


def test_dom_tree_attach_update_detach_lifecycle() -> None:
    """测试会话 DOM 节点挂载、属性变更、脱离递归清理与版本号递增。"""
    tree = SessionDomTree(root_id="root")
    assert tree.version == 1

    # 1. 挂载子消息节点
    patch_msg = SessionDomPatch(
        patch_id="p1",
        op=SessionDomPatchOp.ATTACH_NODE,
        target_node_id="msg_01",
        parent_id="root",
        node_kind=SessionDomNodeKind.MESSAGE,
        attribute_deltas={"role": "user", "content": "请分析架构"},
    )
    v2 = tree.apply_patch(patch_msg)
    assert v2 == 2
    node_msg = tree.get_node("msg_01")
    assert node_msg is not None
    assert node_msg.attributes["content"] == "请分析架构"
    assert "msg_01" in tree.get_node("root").children

    # 2. 更新消息属性
    patch_update = SessionDomPatch(
        patch_id="p2",
        op=SessionDomPatchOp.UPDATE_ATTRS,
        target_node_id="msg_01",
        attribute_deltas={"status": "delivered"},
    )
    v3 = tree.apply_patch(patch_update)
    assert v3 == 3
    assert tree.get_node("msg_01").attributes["status"] == "delivered"
    assert tree.get_node("msg_01").attributes["content"] == "请分析架构"

    # 3. 脱离清理节点
    patch_detach = SessionDomPatch(
        patch_id="p3",
        op=SessionDomPatchOp.DETACH_NODE,
        target_node_id="msg_01",
    )
    v4 = tree.apply_patch(patch_detach)
    assert v4 == 4
    assert tree.get_node("msg_01") is None
    assert "msg_01" not in tree.get_node("root").children


def test_compute_true_rewind_diff_and_worklist() -> None:
    """测试基于 DOM Diff 自动推导真实的生命周期析构工作清单（终止进程、销毁子Agent、还原环境变量）。"""
    tree = SessionDomTree(root_id="root")
    engine = UniversalEventSourcedSessionDomEngine()

    # 阶段 1: 挂载初始环境与消息并生成快照
    p_env = SessionDomPatch(
        patch_id="p_env",
        op=SessionDomPatchOp.ATTACH_NODE,
        target_node_id="env_debug",
        parent_id="root",
        node_kind=SessionDomNodeKind.ENV_VAR,
        attribute_deltas={"key": "DEBUG", "val": "false"},
    )
    tree.apply_patch(p_env)
    target_snapshot = tree.snapshot()
    target_version = tree.version

    # 阶段 2: 演进会话——修改环境变量、启动后台任务、派生子 Agent
    p_env_mod = SessionDomPatch(
        patch_id="p_env_mod",
        op=SessionDomPatchOp.UPDATE_ATTRS,
        target_node_id="env_debug",
        attribute_deltas={"val": "true"},
    )
    p_task = SessionDomPatch(
        patch_id="p_task",
        op=SessionDomPatchOp.ATTACH_NODE,
        target_node_id="task_build_99",
        parent_id="root",
        node_kind=SessionDomNodeKind.BACKGROUND_TASK,
        attribute_deltas={"pid": 9999, "command": "cargo build", "status": "running"},
    )
    p_subagent = SessionDomPatch(
        patch_id="p_subagent",
        op=SessionDomPatchOp.ATTACH_NODE,
        target_node_id="subagent_researcher_01",
        parent_id="root",
        node_kind=SessionDomNodeKind.SUBAGENT,
        attribute_deltas={"role": "Codebase Researcher"},
    )
    engine.apply_patch_stream(tree, [p_env_mod, p_task, p_subagent])

    # 阶段 3: 执行基于 DOM Diff 的绝对真实 Rewind 工作清单计算
    worklist: RewindLifecycleWorklist = engine.compute_true_rewind_worklist(
        current_tree=tree,
        target_snapshot=target_snapshot,
        target_version=target_version,
    )

    assert worklist.from_version == tree.version
    assert worklist.target_version == target_version
    assert worklist.is_pure_idempotent is True

    # 验证精确析构清单
    assert len(worklist.terminated_tasks) == 1
    term_action = worklist.terminated_tasks[0]
    assert term_action.action_type == "TERMINATE_PROCESS"
    assert term_action.target_node_id == "task_build_99"
    assert term_action.metadata["pid"] == 9999

    assert len(worklist.destroyed_subagents) == 1
    sub_action = worklist.destroyed_subagents[0]
    assert sub_action.action_type == "DESTROY_SUBAGENT"
    assert sub_action.target_node_id == "subagent_researcher_01"

    assert len(worklist.reverted_env_vars) == 1
    env_action = worklist.reverted_env_vars[0]
    assert env_action.action_type == "REVERT_ENV"
    assert env_action.target_node_id == "env_debug"


def test_execute_rewind_atomic_restoration() -> None:
    """测试 execute_rewind 原子回退状态树。"""
    tree = SessionDomTree(root_id="root")
    engine = UniversalEventSourcedSessionDomEngine()

    snapshot_v1 = tree.snapshot()
    v1 = tree.version

    # 添加新节点
    patch_msg = SessionDomPatch(
        patch_id="p_new",
        op=SessionDomPatchOp.ATTACH_NODE,
        target_node_id="msg_temp",
        parent_id="root",
        node_kind=SessionDomNodeKind.MESSAGE,
        attribute_deltas={"role": "user", "content": "临时探索"},
    )
    tree.apply_patch(patch_msg)
    assert tree.get_node("msg_temp") is not None

    # 执行原子回滚
    worklist = engine.execute_rewind(tree, snapshot_v1, v1)
    assert tree.version == v1
    assert tree.get_node("msg_temp") is None
    assert worklist.target_version == v1


def test_zero_state_projections() -> None:
    """测试零状态纯投影体系：提取对话消息与活跃任务大盘。"""
    tree = SessionDomTree(root_id="root")
    engine = UniversalEventSourcedSessionDomEngine()

    patches = [
        SessionDomPatch(
            patch_id="p1",
            op=SessionDomPatchOp.ATTACH_NODE,
            target_node_id="m1",
            node_kind=SessionDomNodeKind.MESSAGE,
            attribute_deltas={"role": "user", "content": "你好"},
        ),
        SessionDomPatch(
            patch_id="p2",
            op=SessionDomPatchOp.ATTACH_NODE,
            target_node_id="m2",
            node_kind=SessionDomNodeKind.MESSAGE,
            attribute_deltas={"role": "assistant", "content": "很高兴为您服务"},
        ),
        SessionDomPatch(
            patch_id="p3",
            op=SessionDomPatchOp.ATTACH_NODE,
            target_node_id="t1",
            node_kind=SessionDomNodeKind.BACKGROUND_TASK,
            attribute_deltas={"name": "indexing", "status": "running"},
        ),
        SessionDomPatch(
            patch_id="p4",
            op=SessionDomPatchOp.ATTACH_NODE,
            target_node_id="t2",
            node_kind=SessionDomNodeKind.BACKGROUND_TASK,
            attribute_deltas={"name": "cleanup", "status": "done"},
        ),
    ]
    engine.apply_patch_stream(tree, patches)

    # 1. 对话消息投影
    messages = engine.project_conversation_messages(tree)
    assert len(messages) == 2
    assert messages[0] == {"role": "user", "content": "你好"}
    assert messages[1] == {"role": "assistant", "content": "很高兴为您服务"}

    # 2. 活跃后台任务大盘投影（仅保留 status == running）
    active_tasks = engine.project_active_tasks(tree)
    assert len(active_tasks) == 1
    assert active_tasks[0]["name"] == "indexing"

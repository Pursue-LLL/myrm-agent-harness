"""通用事件溯源会话 DOM、声明式生命周期与真回滚引擎核心实现。

[INPUT]
- session_dom_types.py: 契约模型 (SessionDomNodeKind, SessionDomPatchOp, SessionDomNode, SessionDomPatch, RewindLifecycleAction, RewindLifecycleWorklist)

[OUTPUT]
- SessionDomTree: 单一权威会话 DOM 树
- UniversalEventSourcedSessionDomEngine: 事件流补丁回放、DOM Diff 计算、真回滚生命周期清单推导与零状态纯投影

[POS]
- 位于 context_management/session_dom/session_dom_engine.py
"""

from copy import deepcopy

from .session_dom_types import (
    RewindLifecycleAction,
    RewindLifecycleWorklist,
    SessionDomNode,
    SessionDomNodeKind,
    SessionDomPatch,
    SessionDomPatchOp,
)


class SessionDomTree:
    """物化单一权威会话状态的内存 DOM 树。"""

    def __init__(self, root_id: str = "root") -> None:
        self._version: int = 1
        root_node = SessionDomNode(
            node_id=root_id,
            parent_id=None,
            kind=SessionDomNodeKind.ROOT,
            attributes={"title": "Session Root"},
            children=(),
            version=1,
        )
        self._nodes: dict[str, SessionDomNode] = {root_id: root_node}

    @property
    def version(self) -> int:
        return self._version

    def get_node(self, node_id: str) -> SessionDomNode | None:
        return self._nodes.get(node_id)

    def snapshot(self) -> dict[str, SessionDomNode]:
        """导出当前 DOM 树的只读不可变快照。"""
        return deepcopy(self._nodes)

    def apply_patch(self, patch: SessionDomPatch) -> int:
        """应用单个事件补丁，返回推进后的 DOM 版本号。"""
        self._version += 1

        if patch.op == SessionDomPatchOp.ATTACH_NODE:
            parent_id = patch.parent_id or "root"
            new_node = SessionDomNode(
                node_id=patch.target_node_id,
                parent_id=parent_id,
                kind=patch.node_kind or SessionDomNodeKind.MESSAGE,
                attributes=dict(patch.attribute_deltas),
                children=(),
                version=self._version,
            )
            self._nodes[patch.target_node_id] = new_node

            parent_node = self._nodes.get(parent_id)
            if parent_node:
                updated_children = parent_node.children + (patch.target_node_id,)
                self._nodes[parent_id] = SessionDomNode(
                    node_id=parent_node.node_id,
                    parent_id=parent_node.parent_id,
                    kind=parent_node.kind,
                    attributes=dict(parent_node.attributes),
                    children=updated_children,
                    version=self._version,
                )

        elif patch.op == SessionDomPatchOp.UPDATE_ATTRS:
            existing = self._nodes.get(patch.target_node_id)
            if existing:
                merged_attrs = dict(existing.attributes)
                merged_attrs.update(patch.attribute_deltas)
                self._nodes[patch.target_node_id] = SessionDomNode(
                    node_id=existing.node_id,
                    parent_id=existing.parent_id,
                    kind=existing.kind,
                    attributes=merged_attrs,
                    children=existing.children,
                    version=self._version,
                )

        elif patch.op == SessionDomPatchOp.DETACH_NODE:
            target = self._nodes.get(patch.target_node_id)
            if target:
                if target.parent_id and target.parent_id in self._nodes:
                    parent_node = self._nodes[target.parent_id]
                    updated_children = tuple(c for c in parent_node.children if c != patch.target_node_id)
                    self._nodes[target.parent_id] = SessionDomNode(
                        node_id=parent_node.node_id,
                        parent_id=parent_node.parent_id,
                        kind=parent_node.kind,
                        attributes=dict(parent_node.attributes),
                        children=updated_children,
                        version=self._version,
                    )
                self._recursive_remove(patch.target_node_id)

        return self._version

    def _recursive_remove(self, node_id: str) -> None:
        node = self._nodes.pop(node_id, None)
        if node:
            for child_id in node.children:
                self._recursive_remove(child_id)


class UniversalEventSourcedSessionDomEngine:
    """事件溯源会话 DOM、DOM Diff 计算与真回滚引擎。"""

    def apply_patch_stream(
        self,
        tree: SessionDomTree,
        patches: list[SessionDomPatch],
    ) -> int:
        """顺序应用一批属性变更 Patch 事件流。"""
        for patch in patches:
            tree.apply_patch(patch)
        return tree.version

    def compute_true_rewind_worklist(
        self,
        current_tree: SessionDomTree,
        target_snapshot: dict[str, SessionDomNode],
        target_version: int,
    ) -> RewindLifecycleWorklist:
        """基于当前 DOM 树与目标快照的严谨 DOM Diff，自动推导演进析构与恢复工作清单。

        核心数学公理：
        - 消失的元素即终止（后台进程销毁、子 Agent 释放、环境变量还原）
        - 出现的元素即恢复
        - Diff 本身即为绝对真实的生命周期析构工作清单，消灭状态漂移与死分支残留。
        """
        current_nodes = current_tree.snapshot()

        terminated_tasks: list[RewindLifecycleAction] = []
        destroyed_subagents: list[RewindLifecycleAction] = []
        reverted_env_vars: list[RewindLifecycleAction] = []
        restored_nodes: list[RewindLifecycleAction] = []

        # 1. 检查消失的元素（存在于当前树，但不存在于目标快照）
        for node_id, node in current_nodes.items():
            if node_id not in target_snapshot:
                if node.kind == SessionDomNodeKind.BACKGROUND_TASK:
                    terminated_tasks.append(
                        RewindLifecycleAction(
                            action_type="TERMINATE_PROCESS",
                            target_node_id=node_id,
                            node_kind=node.kind,
                            description=f"终止撤销分支中启动的后台任务 {node_id} (PID: {node.attributes.get('pid', 'N/A')})",
                            metadata=dict(node.attributes),
                        )
                    )
                elif node.kind == SessionDomNodeKind.SUBAGENT:
                    destroyed_subagents.append(
                        RewindLifecycleAction(
                            action_type="DESTROY_SUBAGENT",
                            target_node_id=node_id,
                            node_kind=node.kind,
                            description=f"销毁撤销分支中派生的子 Agent 容器 {node_id}",
                            metadata=dict(node.attributes),
                        )
                    )
                elif node.kind == SessionDomNodeKind.ENV_VAR:
                    reverted_env_vars.append(
                        RewindLifecycleAction(
                            action_type="REVERT_ENV",
                            target_node_id=node_id,
                            node_kind=node.kind,
                            description=f"注销撤销分支中新注入的环境变量 {node.attributes.get('key', node_id)}",
                            metadata=dict(node.attributes),
                        )
                    )

        # 2. 检查被修改的属性或还原值（两边都有但属性变更）
        for node_id, target_node in target_snapshot.items():
            current_node = current_nodes.get(node_id)
            if current_node and current_node.kind == SessionDomNodeKind.ENV_VAR:
                if current_node.attributes != target_node.attributes:
                    reverted_env_vars.append(
                        RewindLifecycleAction(
                            action_type="REVERT_ENV",
                            target_node_id=node_id,
                            node_kind=target_node.kind,
                            description=f"还原环境变量 {target_node.attributes.get('key', node_id)} 到历史版本值",
                            metadata={"target_attrs": target_node.attributes},
                        )
                    )

        # 3. 检查恢复的元素（目标快照有，但当前树中没有）
        for node_id, target_node in target_snapshot.items():
            if node_id not in current_nodes:
                restored_nodes.append(
                    RewindLifecycleAction(
                        action_type="RESTORE_NODE",
                        target_node_id=node_id,
                        node_kind=target_node.kind,
                        description=f"恢复历史节点 {node_id} ({target_node.kind})",
                        metadata=dict(target_node.attributes),
                    )
                )

        total_actions = (
            len(terminated_tasks)
            + len(destroyed_subagents)
            + len(reverted_env_vars)
            + len(restored_nodes)
        )

        return RewindLifecycleWorklist(
            from_version=current_tree.version,
            target_version=target_version,
            terminated_tasks=tuple(terminated_tasks),
            destroyed_subagents=tuple(destroyed_subagents),
            reverted_env_vars=tuple(reverted_env_vars),
            restored_nodes=tuple(restored_nodes),
            total_actions_count=total_actions,
            is_pure_idempotent=True,
        )

    def execute_rewind(
        self,
        tree: SessionDomTree,
        target_snapshot: dict[str, SessionDomNode],
        target_version: int,
    ) -> RewindLifecycleWorklist:
        """执行确定性真回滚：计算生命周期清单并原子还原 DOM 状态。"""
        worklist = self.compute_true_rewind_worklist(tree, target_snapshot, target_version)
        # 原子回滚内存状态
        tree._nodes = deepcopy(target_snapshot)
        tree._version = target_version
        return worklist

    # ================== 零状态纯投影体系 ==================

    def project_conversation_messages(
        self,
        tree: SessionDomTree,
    ) -> tuple[dict[str, str], ...]:
        """将权威 DOM 树纯投影为无副作用的消息历史列表。"""
        messages: list[dict[str, str]] = []
        for node in tree.snapshot().values():
            if node.kind == SessionDomNodeKind.MESSAGE:
                role = str(node.attributes.get("role", "user"))
                content = str(node.attributes.get("content", ""))
                messages.append({"role": role, "content": content})
        return tuple(messages)

    def project_active_tasks(
        self,
        tree: SessionDomTree,
    ) -> tuple[dict[str, str | int | bool], ...]:
        """将权威 DOM 树纯投影为当前正在运行的后台任务大盘。"""
        active: list[dict[str, str | int | bool]] = []
        for node in tree.snapshot().values():
            if node.kind == SessionDomNodeKind.BACKGROUND_TASK:
                if node.attributes.get("status") == "running":
                    active.append(dict(node.attributes))
        return tuple(active)

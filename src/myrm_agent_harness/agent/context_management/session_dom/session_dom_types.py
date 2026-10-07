"""通用事件溯源会话 DOM、声明式生命周期与真回滚引擎强类型契约定义。

[INPUT]
- 无外部动态依赖，定义会话 DOM 节点类型枚举、补丁事件操作、节点实体与回滚生命周期工作清单契约。

[OUTPUT]
- SessionDomNodeKind: DOM 节点类型枚举 (ROOT, MESSAGE, TOOL_CALL, SUBAGENT, BACKGROUND_TASK, TODO_ITEM, ENV_VAR)
- SessionDomPatchOp: DOM Patch 操作枚举 (ATTACH_NODE, UPDATE_ATTRS, DETACH_NODE)
- SessionDomNode: 会话 DOM 节点实体契约
- SessionDomPatch: 事件溯源属性补丁契约
- RewindLifecycleAction: 析构与恢复动作契约
- RewindLifecycleWorklist: 基于 DOM Diff 推导出的权威真回滚工作清单契约

[POS]
- 位于 context_management/session_dom/session_dom_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum


class SessionDomNodeKind(StrEnum):
    """会话权威 DOM 节点分类枚举。"""

    ROOT = "root"
    MESSAGE = "message"
    TOOL_CALL = "tool_call"
    SUBAGENT = "subagent"
    BACKGROUND_TASK = "background_task"
    TODO_ITEM = "todo_item"
    ENV_VAR = "env_var"


class SessionDomPatchOp(StrEnum):
    """会话 DOM 属性补丁事件操作枚举。"""

    ATTACH_NODE = "attach_node"
    UPDATE_ATTRS = "update_attrs"
    DETACH_NODE = "detach_node"


@dataclass(frozen=True)
class SessionDomNode:
    """单一权威会话 DOM 节点契约。"""

    node_id: str
    parent_id: str | None
    kind: SessionDomNodeKind
    attributes: dict[str, str | int | bool]
    children: tuple[str, ...] = ()
    version: int = 1


@dataclass(frozen=True)
class SessionDomPatch:
    """事件溯源变更补丁契约。"""

    patch_id: str
    op: SessionDomPatchOp
    target_node_id: str
    parent_id: str | None = None
    node_kind: SessionDomNodeKind | None = None
    attribute_deltas: dict[str, str | int | bool] = field(default_factory=dict)
    timestamp_iso: str = ""


@dataclass(frozen=True)
class RewindLifecycleAction:
    """单个回滚析构或恢复生命周期动作。"""

    action_type: str  # "TERMINATE_PROCESS" | "DESTROY_SUBAGENT" | "REVERT_ENV" | "RESTORE_NODE"
    target_node_id: str
    node_kind: SessionDomNodeKind
    description: str
    metadata: dict[str, str | int | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class RewindLifecycleWorklist:
    """基于 DOM Diff 推导出的权威真回滚执行清单契约。"""

    from_version: int
    target_version: int
    terminated_tasks: tuple[RewindLifecycleAction, ...]
    destroyed_subagents: tuple[RewindLifecycleAction, ...]
    reverted_env_vars: tuple[RewindLifecycleAction, ...]
    restored_nodes: tuple[RewindLifecycleAction, ...]
    total_actions_count: int
    is_pure_idempotent: bool

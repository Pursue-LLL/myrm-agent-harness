"""通用事件溯源会话 DOM、声明式生命周期与真回滚引擎模块。

[INPUT]
- session_dom_types.py: 契约模型
- session_dom_engine.py: 核心 DOM 树与回滚引擎

[OUTPUT]
- 导出 SessionDomNodeKind, SessionDomPatchOp, SessionDomNode, SessionDomPatch, RewindLifecycleAction, RewindLifecycleWorklist, SessionDomTree, UniversalEventSourcedSessionDomEngine

[POS]
- 位于 context_management/session_dom/__init__.py
"""

from .session_dom_engine import (
    SessionDomTree,
    UniversalEventSourcedSessionDomEngine,
)
from .session_dom_types import (
    RewindLifecycleAction,
    RewindLifecycleWorklist,
    SessionDomNode,
    SessionDomNodeKind,
    SessionDomPatch,
    SessionDomPatchOp,
)

__all__ = [
    "RewindLifecycleAction",
    "RewindLifecycleWorklist",
    "SessionDomNode",
    "SessionDomNodeKind",
    "SessionDomPatch",
    "SessionDomPatchOp",
    "SessionDomTree",
    "UniversalEventSourcedSessionDomEngine",
]

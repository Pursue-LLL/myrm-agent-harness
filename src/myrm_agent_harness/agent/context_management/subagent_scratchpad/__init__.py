"""多代理共享草稿白板、子代理瞬态上下文隔离与轻量事实广播套件模块。

[INPUT]
- subagent_scratchpad_types.py: 契约模型
- subagent_scratchpad_engine.py: 核心引擎实现

[OUTPUT]
- 导出 FactCategory, SubagentLifecycleStatus, SharedScratchpadFact, EphemeralSubagentDossier, ScratchpadQueryFilter, MultiAgentSharedScratchpadEngine

[POS]
- 位于 context_management/subagent_scratchpad/__init__.py
"""

from .subagent_scratchpad_engine import MultiAgentSharedScratchpadEngine
from .subagent_scratchpad_types import (
    EphemeralSubagentDossier,
    FactCategory,
    ScratchpadQueryFilter,
    SharedScratchpadFact,
    SubagentLifecycleStatus,
)

__all__ = [
    "EphemeralSubagentDossier",
    "FactCategory",
    "MultiAgentSharedScratchpadEngine",
    "ScratchpadQueryFilter",
    "SharedScratchpadFact",
    "SubagentLifecycleStatus",
]

# working_memory/

## Overview
Agent working memory meta-tool module. Provides LLM-facing autonomous 5-action space controls to update subtask steps, discard dead-ends with automatic trap avoidance registration, summarize multi-step stages, and maintain lightweight transient memos on `LocalWorkingMemoryBlock`.

Detailed design: [MEMORY_SYSTEM.md](../../../toolkits/memory/MEMORY_SYSTEM.md)

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|:-----:|
| `__init__.py` | 辅助 | 导出 `create_working_memory_manage_tool` | ✅ |
| `working_memory_agent_tools.py` | 核心 | 提供 `working_memory_manage_tool` 元工具与自定义事件派发 | ✅ |


## Architectural Constraints
1. **Prompt Cache Safety**: Works strictly in tandem with dynamic Turn Tail `<working_board>`. Never mutates static system prompt prefixes.
2. **Boundary Protection**: Resides in `agent/meta_tools/`, safely interacting with `LocalWorkingMemoryBlock` (`agent/context_management/`). Keeps `toolkits/` 100% free of reverse dependencies.
3. **Dead-End Healing**: When action is `discard`, automatically generates a `TrapRecord` registered on `LocalWorkingMemoryBlock` to eliminate repetitive failure loops.

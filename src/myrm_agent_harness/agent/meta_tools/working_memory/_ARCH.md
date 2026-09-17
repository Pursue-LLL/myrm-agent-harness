# working_memory/

## Overview
Agent working memory meta-tool module. Provides LLM-facing autonomous 5-action space controls to update subtask steps, discard dead-ends with automatic trap avoidance registration, summarize multi-step stages, and maintain lightweight transient memos on `LocalWorkingMemoryBlock`.

Detailed design: [MEMORY_SYSTEM.md](../../../toolkits/memory/MEMORY_SYSTEM.md)

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Exports `create_working_memory_manage_tool`. |
| `working_memory_agent_tools.py` | Core Tool | LangChain tool `working_memory_manage_tool` with self-healing validation and SSE event dispatch. |

## Architectural Constraints
1. **Prompt Cache Safety**: Works strictly in tandem with dynamic Turn Tail `<working_board>`. Never mutates static system prompt prefixes.
2. **Boundary Protection**: Resides in `agent/meta_tools/`, safely interacting with `LocalWorkingMemoryBlock` (`agent/context_management/`). Keeps `toolkits/` 100% free of reverse dependencies.
3. **Dead-End Healing**: When action is `discard`, automatically generates a `TrapRecord` registered on `LocalWorkingMemoryBlock` to eliminate repetitive failure loops.

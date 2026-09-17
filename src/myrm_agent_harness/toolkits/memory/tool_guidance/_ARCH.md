# Architecture - tool_guidance

Tool memory procedural contract and deterministic synthesis domain layer.

## Module Role

This subpackage consolidates procedural memory entries, traps, and edicts into a deterministic, cache-stable golden guidance set for active tools. It operates strictly zero-LLM cost, sub-millisecond execution, and bounded output.

## File Manifest

| File | Tier | Responsibility | Tested |
|------|------|----------------|--------|
| `__init__.py` | Facade | Unified domain facade exporting types and synthesizer functions. | ✅ |
| `types.py` | Core | Immutable dataclasses `ToolGuidanceItem` and `ToolGuidanceSummary`. | ✅ |
| `synthesizer.py` | Core | Pure-functional probe command filter, budget cap, and Cache-Stable synthesizer. | ✅ |

## Design Invariants

1. **Zero-LLM Overhead**: All operations are pure functions with sub-millisecond complexity (O(N log N) deterministic sort).
2. **Deterministic Cache Stability**: Output strings are strictly ordered alphabetically by tool name and guideline text to preserve LLM provider KV Cache.
3. **Bounded Context**: Hard-capped by `MAX_GUIDELINES_PER_TOOL = 3`, `MAX_TOTAL_TOOL_GUIDELINES = 9`, and `MAX_CHARS_PER_GUIDELINE = 160`.

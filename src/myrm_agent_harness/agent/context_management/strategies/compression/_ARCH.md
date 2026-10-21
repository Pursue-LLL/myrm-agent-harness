# compression/

## Overview
Anti-thrash guards and effectiveness tracking for automatic compression paths.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports compression guard APIs. | — |
| compression_anti_thrash_guard.py | Core | Decides whether to block automatic compression based on ineffective streak and safety-net ratio. | ✅ |
| compression_formatting.py | Core | Shared formatting utilities for compressed content (identifier extraction, content generation, tool-call arg shrinking). | ✅ |
| compression_streak_store.py | Core | Pluggable streak persistence protocol for server DB-backed streak without reverse SQL dependency in harness. | ✅ |

## Key Dependencies

- `...infra.schemas` (CompactToolCall)
- `...tracking.task_metrics`

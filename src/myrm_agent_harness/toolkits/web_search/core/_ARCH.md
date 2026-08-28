# core/

## Overview
Shared data models, exception hierarchy, error classification, and in-process metrics for web search.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports common types, exceptions, error helpers, metrics | ✅ |
| common.py | Core | SearchResult and Citation data models | ✅ |
| exceptions.py | Core | Web search exception hierarchy with format_for_llm | ✅ |
| error_handling.py | Core | Search failure classification and ErrorContext SSOT | ✅ |
| metrics.py | Core | Thread-safe in-process search counters | ✅ |

## Dependencies

- `utils.text_cleaner`

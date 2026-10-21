# core/

## Overview
Shared data models, exception hierarchy, and error classification for web search.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports common types, exceptions, error helpers | ✅ |
| common.py | Core | SearchResult and Citation data models | ✅ |
| exceptions.py | Core | Web search exception hierarchy with format_for_llm; SearchAPIError text carries status and code but never the user query, so classifiers cannot read the query as a failure signal | ✅ |
| error_handling.py | Core | Search failure classification and ErrorContext SSOT | ✅ |

## Dependencies

- `utils.text_cleaner`

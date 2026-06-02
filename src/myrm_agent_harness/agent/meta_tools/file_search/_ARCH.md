# file_search/

## Overview
File search tool module (Claude Code compatible). Provides file name search and AST-aware content search
with structured output (symbol grouping, intelligent line truncation).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | File search tool module exports | — |
| glob_tool.py | Core | File search tool. Searches for files using glob patterns (* and **) | ✅ |
| grep_tool.py | Core | Content search tool. AST-aware structured output with symbol grouping, line truncation, non-code capping. Three-tier search engine (ripgrep > mmap > Python) | ✅ |
| _formatter.py | Internal | Grep result formatter. Structured output logic (symbol grouping, line truncation, non-code capping) extracted from grep_tool | ✅ |
| regex_validator.py | Core | Regex safety validator (ReDoS protection) | ✅ |

## Key Dependencies

- `toolkits.code_execution` (executor for path resolution)
- `utils` (LRUCache, ToolError)

# file_search/

## Overview
File search tool module (Claude Code compatible). Provides file name search and content search
with flat path:line output and intelligent line truncation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | File search tool module exports | — |
| glob_tool.py | Core | File search tool. Searches for files using glob patterns (* and **) | ✅ |
| grep_tool.py | Core | Content search tool. Flat path:line output, line truncation, non-code capping. Three-tier search engine (ripgrep > mmap > Python) | ✅ |
| _formatter.py | Internal | Grep result formatter. Line truncation and non-code capping | ✅ |
| regex_validator.py | Core | Regex safety validator (ReDoS protection) | ✅ |

## Key Dependencies

- `toolkits.code_execution` (executor for path resolution)
- `utils` (LRUCache, ToolError)

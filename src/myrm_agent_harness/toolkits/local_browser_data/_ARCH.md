# local_browser_data/

## Overview
Local browser data search toolkit entry point. Exports the tool factory function.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Local browser data search toolkit entry point. Exports the tool factory function. | ✅ |
| bookmark_searcher.py | Core | Chromium bookmark retriever. Recursively traverses Bookmarks JSON file, | ✅ |
| chromium_locator.py | Core | Cross-platform Chromium data directory detector. Supports Chrome and Edge (both Chromium-based, | ✅ |
| history_searcher.py | Core | Chromium browsing history searcher. Copies History SQLite to temp directory to avoid browser write-l | ✅ |
| local_browser_data_agent_tools.py | Core | LangChain interface layer for local browser data search tool. Wraps underlying search capabilities | ✅ |
| profile_enumerator.py | Core | Chromium multi-profile enumerator. Parses Local State JSON to discover all user profiles, | ✅ |
| types.py | Config | Data type definitions for local browser data search. Pure data structures, no business logic. | ✅ |

## Key Dependencies

- `diagnostics`

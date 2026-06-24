# rss/

## Overview

RSS/Atom feed fetching and parsing toolkit. Zero external dependency for
XML parsing (stdlib `xml.etree`); uses `httpx` for async HTTP. Agents can
consume structured feed entries without wasting tokens on raw XML.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `rss_agent_tools.py` | Core | `create_rss_tool` factory — RSS 2.0 / Atom / RDF 1.0 parser | ✅ |
| `__init__.py` | Package | Public exports | — |

## Dependencies

- No `agent/` imports (toolkits gate)
- `httpx` (async HTTP client)
- `xml.etree.ElementTree` (stdlib)

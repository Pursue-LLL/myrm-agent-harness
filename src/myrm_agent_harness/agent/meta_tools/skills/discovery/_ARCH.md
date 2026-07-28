# discovery/

## Overview
Legacy skill discovery package. External marketplace install lives under `skills/market/` (`skill_market_tool`). Agent-bound library search uses `discover_capability` (`skill_search_tool`).

**Boundary**: For skills already bound to the agent, use `skill_search_tool` + `skill_select_tool`. For external marketplace install, use `skill_market_tool` when Turn1-mounted, or product Settings → Skills → Discover.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill discovery package marker. | — |
| skill_discovery_tool.py | Legacy | Historical discovery helper; prefer `discover_capability` meta-tool. | ✅ |

## Key Dependencies

- `backends`

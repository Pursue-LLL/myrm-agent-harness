# discovery/

## Overview
External marketplace skill install/uninstall meta-tool (LLM-facing name: `skill_market_tool`). Turn1 eager when `discovery_backend` is provided.

**Boundary**: searches and installs from **external sources** (GitHub, skills.sh, etc.). For skills already bound to the agent, use `skill_search_tool` + `skill_select_tool` instead.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill discovery meta-tool. | — |
| skill_discovery_tool.py | Core | Skill market meta-tool (LLM name: `skill_market_tool`). | ✅ |

## Key Dependencies

- `backends`

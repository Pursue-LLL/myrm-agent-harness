# market/

## Overview
External marketplace skill install/uninstall meta-tool (LLM-facing name: `skill_market_tool`). **产品层**在 `enable_skill_market` 等开关为 ON 时 Turn1 mount；`get_meta_tools` 不再默认创建。

**Boundary**: searches and installs from **external sources** (GitHub, skills.sh, etc.). For skills already bound to the agent, use `skill_search_tool` + `skill_select_tool` instead.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill market meta-tool. | — |
| skill_market_tool.py | Core | Skill market meta-tool (LLM name: `skill_market_tool`). | ✅ |

## Key Dependencies

- `backends`
